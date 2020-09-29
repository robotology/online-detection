import os
import errno
import sys

from accuracy_evaluator_detector import AccuracyEvaluatorDetector
basedir = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(basedir, os.path.pardir)))
from AccuracyEvaluatorAbstract import AccuracyEvaluatorAbstract


class AccuracyEvaluator(AccuracyEvaluatorAbstract):
    def __init__(self, cfg_path_target_task=None, cfg_path_RPN=None, train_in_cpu=False):
        self.cfg_path_target_task = cfg_path_target_task
        self.cfg_path_RPN = cfg_path_RPN
        self.falkon_rpn_models = None
        self.regressors_rpn_models = None
        self.stats_rpn = None
        self.falkon_detector_models = None
        self.regressors_detector_models = None
        self.stats_detector = None
        self.regions_post_nms = None
        self.train_in_cpu = train_in_cpu

    def evaluateAccuracyDetection(self, is_train, output_dir=None, save_features=False):
        # call class to extract detector features:
        accuracy_evaluator = AccuracyEvaluatorDetector(self.cfg_path_target_task)
        accuracy_evaluator.falkon_rpn_models = self.falkon_rpn_models
        accuracy_evaluator.regressors_rpn_models = self.regressors_rpn_models
        accuracy_evaluator.stats_rpn = self.stats_rpn
        accuracy_evaluator.falkon_detector_models = self.falkon_detector_models
        accuracy_evaluator.regressors_detector_models = self.regressors_detector_models
        accuracy_evaluator.stats_detector = self.stats_detector
        if self.regions_post_nms is not None:
            accuracy_evaluator.cfg.MODEL.RPN.POST_NMS_TOP_N_TEST = self.regions_post_nms
        features = accuracy_evaluator(is_train, output_dir=output_dir, train_in_cpu=self.train_in_cpu, save_features=save_features)

        return features
