from mrcnn_modified.modeling.roi_heads.box_head.inference import PostProcessor
import torch.nn.functional as F
import torch

from maskrcnn_benchmark.structures.bounding_box import BoxList
from maskrcnn_benchmark.structures.boxlist_ops import boxlist_nms
from maskrcnn_benchmark.structures.boxlist_ops import cat_boxlist


class OnlineDetectionPostProcessor(PostProcessor):
    def forward(self, boxes, num_classes):
        """
        Arguments:
            x (tuple[tensor, tensor]): x contains the class logits
                and the box_regression from the model.
            boxes (list[BoxList]): bounding boxes that are used as
                reference, one for ech image
        Returns:
            results (list[BoxList]): one BoxList for each image, containing
                the extra fields labels and scores
        """
        # class_logits, proposals = x
        # class_prob = F.softmax(torch.from_numpy(class_logits))
        # class_prob = torch.from_numpy(class_logits)
        # proposals = torch.from_numpy(proposals)

        # image_shapes = [box.size for box in boxes]
        # boxes_per_image = [len(box) for box in boxes]
        # concat_boxes = torch.cat([a.bbox for a in boxes], dim=0)

        # if self.cls_agnostic_bbox_reg:
        #     box_regression = box_regression[:, -4:]
        # proposals = self.box_coder.decode(
        #     box_regression.view(sum(boxes_per_image), -1), concat_boxes
        # )
        # if self.cls_agnostic_bbox_reg:
        #     proposals = proposals.repeat(1, class_prob.shape[1])

        # num_classes = class_prob.shape[1]

        # proposals = proposals.split(boxes_per_image, dim=0)
        # class_prob = class_prob.split(boxes_per_image, dim=0)

        results = []
        # for prob, boxes_per_img, image_shape in zip(
        #         class_prob, proposals, image_shapes
        # ):
        #     boxlist = self.prepare_boxlist(boxes_per_img, prob, image_shape)
        #     boxlist = boxlist.clip_to_image(remove_empty=False)
        #     boxlist = self.filter_results(boxlist, num_classes)
        #     results.append(boxlist)

        for box in boxes:
            if self.cls_agnostic_bbox_reg:
                box.bbox = box.bbox.repeat(1, num_classes)
            boxlist = self.prepare_boxlist(box.bbox, box.get_field('scores'), box.size)
            boxlist = boxlist.clip_to_image(remove_empty=False)
            boxlist = self.filter_results(boxlist, num_classes)
            results.append(boxlist)
        return results

    def filter_results(self, boxlist, num_classes):
        """Returns bounding-box detection results by thresholding on scores and
        applying non-maximum suppression (NMS).
        """
        # unwrap the boxlist to avoid additional overhead.
        # if we had multi-class NMS, we could perform this directly on the boxlist
        boxes = boxlist.bbox.reshape(-1, num_classes * 4)
        scores = boxlist.get_field("scores").reshape(-1, num_classes)

        device = scores.device
        result = []
        # Apply threshold on detection probabilities and apply NMS
        # Skip j = 0, because it's the background class
        inds_all = scores > self.score_thresh
        for j in range(1, num_classes):
            inds = inds_all[:, j].nonzero().squeeze(1)
            scores_j = scores[inds, j]
            boxes_j = boxes[inds, j * 4 : (j + 1) * 4]
            boxlist_for_class = BoxList(boxes_j.to('cuda'), boxlist.size, mode="xyxy")
            boxlist_for_class.add_field("scores", scores_j.to('cuda'))
            boxlist_for_class = boxlist_nms(
                boxlist_for_class, self.nms
            )
            num_labels = len(boxlist_for_class)
            boxlist_for_class.add_field(
                "labels", torch.full((num_labels,), j, dtype=torch.int64, device=device)
            )
            result.append(boxlist_for_class)

        result = cat_boxlist(result)
        number_of_detections = len(result)

        # Limit to max_per_image detections **over all classes**
        if number_of_detections > self.detections_per_img > 0:
            cls_scores = result.get_field("scores")
            image_thresh, _ = torch.kthvalue(
                cls_scores.cpu(), number_of_detections - self.detections_per_img + 1
            )
            keep = cls_scores >= image_thresh.item()
            keep = torch.nonzero(keep).squeeze(1)
            result = result[keep]
        return result
