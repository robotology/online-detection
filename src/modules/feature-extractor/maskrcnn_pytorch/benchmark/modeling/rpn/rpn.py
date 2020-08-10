# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
import torch
import torch.nn.functional as F
from torch import nn

from maskrcnn_pytorch.benchmark.modeling import registry
from maskrcnn_benchmark.modeling.box_coder import BoxCoder
from maskrcnn_benchmark.modeling.rpn.retinanet.retinanet import build_retinanet
from .loss import make_rpn_loss_evaluator
from .anchor_generator import make_anchor_generator
from .inference import make_rpn_postprocessor

import time
from .average_recall import compute_average_recall

class RPNHeadConvRegressor(nn.Module):
    """
    A simple RPN Head for classification and bbox regression
    """

    def __init__(self, cfg, in_channels, num_anchors):
        """
        Arguments:
            cfg              : config
            in_channels (int): number of channels of the input feature
            num_anchors (int): number of anchors to be predicted
        """
        super(RPNHeadConvRegressor, self).__init__()
        self.cls_logits = nn.Conv2d(in_channels, num_anchors, kernel_size=1, stride=1)
        self.bbox_pred = nn.Conv2d(
            in_channels, num_anchors * 4, kernel_size=1, stride=1
        )

        for l in [self.cls_logits, self.bbox_pred]:
            torch.nn.init.normal_(l.weight, std=0.01)
            torch.nn.init.constant_(l.bias, 0)

    def forward(self, x):
        assert isinstance(x, (list, tuple))
        logits = [self.cls_logits(y) for y in x]
        bbox_reg = [self.bbox_pred(y) for y in x]

        return logits, bbox_reg


class RPNHeadFeatureSingleConv(nn.Module):
    """
    Adds a simple RPN Head with one conv to extract the feature
    """

    def __init__(self, cfg, in_channels):
        """
        Arguments:
            cfg              : config
            in_channels (int): number of channels of the input feature
        """
        super(RPNHeadFeatureSingleConv, self).__init__()
        self.conv = nn.Conv2d(
            in_channels, in_channels, kernel_size=3, stride=1, padding=1
        )

        for l in [self.conv]:
            torch.nn.init.normal_(l.weight, std=0.01)
            torch.nn.init.constant_(l.bias, 0)

        self.out_channels = in_channels

    def forward(self, x):
        assert isinstance(x, (list, tuple))
        x = [F.relu(self.conv(z)) for z in x]

        return x

@registry.RPN_HEADS.register("OnlineRPNHead")
class RPNHead(nn.Module):
    """
    Adds a simple RPN Head with classification and regression heads
    """

    def __init__(self, cfg, in_channels, num_anchors):
        """
        Arguments:
            cfg              : config
            in_channels (int): number of channels of the input feature
            num_anchors (int): number of anchors to be predicted
        """
        super(RPNHead, self).__init__()
        self.conv = nn.Conv2d(
            in_channels, in_channels, kernel_size=3, stride=1, padding=1
        )
        self.cls_logits = nn.Conv2d(in_channels, num_anchors, kernel_size=1, stride=1)
        self.bbox_pred = nn.Conv2d(
            in_channels, num_anchors * 4, kernel_size=1, stride=1
        )

        for l in [self.conv, self.cls_logits, self.bbox_pred]:
            torch.nn.init.normal_(l.weight, std=0.01)
            torch.nn.init.constant_(l.bias, 0)

        self.feat_size = None
        self.height = None
        self.width = None
        self.num_clss = num_anchors


    def forward(self, x):
        logits = []
        bbox_reg = []
        for feature in x:
            t = F.relu(self.conv(feature))
            # If FALKON classifiers, regressors and stats are defined use online pipeline
            if hasattr(self, 'classifiers'):
                if self.feat_size is None:
                    features_map_size = t.size()
                    self.feat_size = features_map_size[1]
                    self.height = features_map_size[2]
                    self.width = features_map_size[3]
                # Flatten feature map
                t = t.permute(0,2,3,1).view(self.height*self.width,self.feat_size)
                # Normalize features
                t = t - self.stats['mean']
                t = t * (20 / self.stats['mean_norm'].item())
                # Compute objectness with FALKON
                logits.append(self.compute_objectness_FALKON(t))
                # Refine boxes
                bbox_reg.append(self.refine_boxes(t))
            # Else use pretrained weights
            else:
                logits.append(self.cls_logits(t))
                bbox_reg.append(self.bbox_pred(t))
        return logits, bbox_reg

    def refine_boxes(self, features):
        self.num_clss = 15
        refined_boxes = torch.empty((1, 0, self.height, self.width), device='cuda')
        for j in range(self.num_clss):
            # Refine boxes with RLS regressors
            if self.regressors[j]['Beta'] is not None:
                weights = torch.empty((0,self.feat_size+1), device='cuda') #TODO read this value automatically
                for k in range(0, 4):
                    weights = torch.cat((weights, self.regressors[j]['Beta'][str(k)]['weights'].view(1,self.feat_size+1)))#TODO read this value automatically

                weights = torch.t(weights)
                Y = torch.matmul(features, weights[:-1])
                Y += weights[-1]
                Y = torch.matmul(Y, self.regressors[j]['T_inv'])
                Y += self.regressors[j]['mu']
            # If the regressor is not available, do not refine the boxes
            else:
                Y = torch.zeros((self.height*self.width, 4), device='cuda')
            Y = torch.t(Y).reshape(1,4,self.height,self.width)
            refined_boxes = torch.cat((refined_boxes, Y), dim=1)
        return refined_boxes
    
    def compute_objectness_FALKON(self, features):
        objectness_scores = torch.empty((1, 0, self.height, self.width), device='cuda')
        for classifier in self.classifiers:
            # If the classifier is not available, set the objectness to the default value -2 (which is smaller than all the other proposed values by trained FALKON classifiers)
            if classifier is None:
                predictions = torch.full((self.height*self.width, 1), -2, device='cuda')
            # Compute objectness with falkon classifier
            else:
                predictions = classifier.predict(features)
            objectness_scores = torch.cat((objectness_scores, torch.t(predictions).reshape(1,1,self.height,self.width)), dim=1)
        return objectness_scores


class RPNModule(torch.nn.Module):
    """
    Module for RPN computation. Takes feature maps from the backbone and outputs 
    RPN proposals and losses. Works for both FPN and non-FPN.
    """

    def __init__(self, cfg, in_channels):
        super(RPNModule, self).__init__()

        self.cfg = cfg.clone()

        anchor_generator = make_anchor_generator(cfg)

        rpn_head = registry.RPN_HEADS[cfg.MODEL.RPN.RPN_HEAD]
        head = rpn_head(
            cfg, in_channels, anchor_generator.num_anchors_per_location()[0]
        )

        rpn_box_coder = BoxCoder(weights=(1.0, 1.0, 1.0, 1.0))

        box_selector_train = make_rpn_postprocessor(cfg, rpn_box_coder, is_train=True)
        box_selector_test = make_rpn_postprocessor(cfg, rpn_box_coder, is_train=False)

        loss_evaluator = make_rpn_loss_evaluator(cfg, rpn_box_coder)

        self.anchor_generator = anchor_generator
        self.head = head
        self.box_selector_train = box_selector_train
        self.box_selector_test = box_selector_test
        self.loss_evaluator = loss_evaluator
        self.anchors = None

    def forward(self, images, features, targets=None, compute_average_recall_RPN = False):
        """
        Arguments:
            images (ImageList): images for which we want to compute the predictions
            features (list[Tensor]): features computed from the images that are
                used for computing the predictions. Each tensor in the list
                correspond to different feature levels
            targets (list[BoxList): ground-truth boxes present in the image (optional)

        Returns:
            boxes (list[BoxList]): the predicted boxes from the RPN, one BoxList per
                image.
            losses (dict[Tensor]): the losses for the model during training. During
                testing, it is an empty dict.
        """
        objectness, rpn_box_regression = self.head(features)
        if self.anchors is None:
            self.anchors = self.anchor_generator(images, features)

        if self.training:
            return self._forward_train(self.anchors, objectness, rpn_box_regression, targets, compute_average_recall_RPN = compute_average_recall_RPN)
        else:
            return self._forward_test(self.anchors, objectness, rpn_box_regression, targets = targets, compute_average_recall_RPN = compute_average_recall_RPN)

    def _forward_train(self, anchors, objectness, rpn_box_regression, targets, compute_average_recall_RPN = False):
        if self.cfg.MODEL.RPN_ONLY:
            # When training an RPN-only model, the loss is determined by the
            # predicted objectness and rpn_box_regression values and there is
            # no need to transform the anchors into predicted boxes; this is an
            # optimization that avoids the unnecessary transformation.
            boxes = anchors
        else:
            # For end-to-end models, anchors must be transformed into boxes and
            # sampled into a training batch.
            with torch.no_grad():
                boxes = self.box_selector_train(
                    anchors, objectness, rpn_box_regression, targets
                )
        #loss_objectness, loss_rpn_box_reg = self.loss_evaluator(
        #    anchors, objectness, rpn_box_regression, targets
        #)
        #losses = {
        #    "loss_objectness": loss_objectness,
        #    "loss_rpn_box_reg": loss_rpn_box_reg,
        #}
        #return boxes, losses, 0
        return boxes, {}, 0

    def _forward_test(self, anchors, objectness, rpn_box_regression, targets = None, compute_average_recall_RPN = False):
        boxes = self.box_selector_test(anchors, objectness, rpn_box_regression)
        if self.cfg.MODEL.RPN_ONLY:
            # For end-to-end models, the RPN proposals are an intermediate state
            # and don't bother to sort them in decreasing score order. For RPN-only
            # models, the proposals are the final output and we return them in
            # high-to-low confidence order.
            inds = [
                box.get_field("objectness").sort(descending=True)[1] for box in boxes
            ]
            boxes = [box[ind] for box, ind in zip(boxes, inds)]
        if compute_average_recall_RPN:
            return boxes, {}, compute_average_recall(targets, boxes[0])
        return boxes, {}, None


def build_rpn(cfg, in_channels):
    """
    This gives the gist of it. Not super important because it doesn't change as much
    """
    if cfg.MODEL.RETINANET_ON:
        return build_retinanet(cfg, in_channels)

    return RPNModule(cfg, in_channels)
   
