import os
import sys

basedir = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(basedir, '..', '..')))
sys.path.append(os.path.abspath(os.path.join(basedir, os.path.pardir, 'src', 'modules', 'region-classifier')))
sys.path.append(os.path.abspath(os.path.join(basedir, os.path.pardir, 'src', 'modules', 'accuracy-evaluator')))
sys.path.append(os.path.abspath(os.path.join(basedir, '..', 'src', 'modules', 'feature-extractor')))
sys.path.append(os.path.abspath(os.path.join(basedir, '..', 'src', 'modules', 'region-refiner')))
sys.path.append(os.path.abspath(os.path.join(basedir, '..', 'src')))


from maskrcnn_pytorch.benchmark.data import make_data_loader
from maskrcnn_pytorch.benchmark.config import cfg

import OnlineRegionClassifier as ocr
import FALKONWrapper as falkon
import MinibootstrapSelector as ms
import AccuracyEvaluator as ae
from feature_extractor import FeatureExtractor
from region_refiner import RegionRefiner


# Temporary imports
import torch

# ----------------------------------------------------------------------------------------
# ------------------------------- Experiment configuration -------------------------------
# ----------------------------------------------------------------------------------------

# Test dataset creation
cfg.merge_from_file('Configs/first_experiment_elisa_server.yaml')
cfg.freeze()
dataset = make_data_loader(cfg, is_train=False, is_distributed=False, is_target_task=True)

# Region Classifier initialization
cfg_path_cls = 'Configs/config_region_classifier_elisa_server.yaml'
classifier = falkon.FALKONWrapper()
negative_selector = ms.MinibootstrapSelector(cfg_path_cls)
regionClassifier = ocr.OnlineRegionClassifier(classifier, negative_selector, cfg_path=cfg_path_cls)

# Feature extraction initialization
feature_extractor = FeatureExtractor('first_experiment/configs/config_feature_task_elisa_server.yaml',
                                     'first_experiment/configs/config_target_task_FALKON_elisa_server.yaml')
# region refiner initialization
region_refiner = RegionRefiner('first_experiment/configs/config_region_refiner_elisa_server.yaml')

# Accuracy evaluator initialization
accuracy_evaluator = ae.AccuracyEvaluator(cfg_path_cls)

# ----------------------------------------------------------------------------------
# ------------------------------- Feature extraction -------------------------------
# ----------------------------------------------------------------------------------

# Retrieve feature extractor (either by loading it or by training it)
print('Retrieve or train feature extractor')
try:
    feature_extractor.loadFeatureExtractor()
except OSError:
    print('Feature extractor will be trained from scratch.')
    feature_extractor.trainFeatureExtractor()

# Extract features for the train/val/test sets
print('Extract features from dataset if needed')
feature_extractor.extractFeatures()

# -----------------------------------------------------------------------------------
# --------------------------------- Training models ---------------------------------
# -----------------------------------------------------------------------------------

# Train region refiner
print('Train region refiner')
regressors = region_refiner.trainRegionRefiner()

# Start the cross validation
print('Skip cross validation')

# - Train region classifier
model = regionClassifier.trainRegionClassifier()

# - Test region classifier (on validation set)
print('Skip Test region classifier on validation set')

# - Test region refiner (on validation set)
print('Skip Test region refiner on validation set')

# - Save/store results
print('Skip saving model')

# ----------------------------------------------------------------------------------
# --------------------------------- Testing models ---------------------------------
# ----------------------------------------------------------------------------------

# Test the best classifier on the test set
print('Region classifier test on the test set')
predictions = regionClassifier.testRegionClassifier(model)
region_refiner.boxes = predictions

print('Region classifier predictions evaluation')
result_cls = accuracy_evaluator.evaluate(dataset.dataset, predictions, is_target_task=True,
                                         cls_agnostic_bbox_reg=True)

# Test the best regressor on the test set
print('Region refiner test on the test set')
refined_predictions = region_refiner.predict()

print('Region classifier predictions evaluation')
result_reg = accuracy_evaluator.evaluate(dataset.dataset, refined_predictions, is_target_task=True,
                                         cls_agnostic_bbox_reg=False)
