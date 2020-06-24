import sys
import os

basedir = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(basedir, os.path.pardir)))
sys.path.append(os.path.abspath(os.path.join(basedir, '..', '..')))

import RegionClassifierAbstract as rcA
from py_od_utils import computeFeatStatistics, zScores, loadFeature
import h5py
import numpy as np
import torch
from maskrcnn_benchmark.structures.bounding_box import BoxList
import time


class OnlineRegionClassifier(rcA.RegionClassifierAbstract):

    def loadRegionClassifier(self) -> None:
        pass

    def processOptions(self, opts):
        if 'num_classes' in opts:
            self.num_classes = opts['num_classes']
        if 'imset_train' in opts:
            self.train_imset = opts['imset_train']
        if 'classifier_options' in opts:
            self.classifier_options = opts['classifier_options']
        if 'is_rpn' in opts:
            self.is_rpn = opts['is_rpn']
        if 'lam' in opts:
            self.lam = opts['lam']
        if 'sigma' in opts:
            self.sigma = opts['sigma']

    # def selectPositives(self, feat_type='h5'):
    #     feat_path = os.path.join(basedir, '..', '..', '..', 'Data', 'feat_cache', self.feature_folder)
    #     positives_file = os.path.join(feat_path, 'positives')
    #     try:
    #         if feat_type == 'mat':
    #             mat_positives = h5py.File(positives_file, 'r')
    #             X_pos = mat_positives['X_pos']
    #             positives_torch = []
    #             for i in range(self.num_classes-1):
    #                 positives_torch.append(mat_positives[X_pos[0, i]][()].transpose())
    #         elif feat_type == 'h5':
    #             positives_dataset = h5py.File(positives_file, 'r')['list']
    #             positives_torch = []
    #             for i in range(self.num_classes-1):
    #                 positives_torch.append(torch.tensor(np.asfortranarray(np.array(positives_dataset[str(i)]))))
    #         else:
    #             print('Unrecognized type of feature file')
    #             positives_torch = None
    #     except:
    #         with open(self.train_imset, 'r') as f:
    #             path_list = f.readlines()
    #         feat_path = os.path.join(basedir, '..', '..', '..', 'Data', 'feat_cache', self.feature_folder, 'trainval')
    #         positives = []
    #         for i in range(len(path_list)):
    #             l = loadFeature(feat_path, path_list[i].rstrip())
    #             for c in range(self.num_classes - 1):
    #                 if len(positives) < c + 1:
    #                     positives.append([])  # Initialization for class c-th
    #                 sel = np.where(l['class'] == c + 1)[0]  # TO CHECK BECAUSE OF MATLAB 1
    #                                                         # INDEXING Moreover class 0 is bkg
    #                 if len(sel):
    #                     if len(positives[c]) == 0:
    #                         positives[c] = l['feat'][sel, :]
    #                     else:
    #                         positives[c] = np.vstack((positives[c], l['feat'][sel, :]))
    #         hf = h5py.File(positives_file, 'w')
    #         grp = hf.create_group('list')
    #         for i in range(self.num_classes - 1):
    #             grp.create_dataset(str(i), data=positives[i])
    #         hf.close()
    #
    #         positives_torch = []
    #         for i in range(self.num_classes - 1):
    #             # for j in range(self.iterations):
    #                 positives_torch.append(torch.tensor(positives[i].reshape(positives[i].shape[0], positives[i].shape[1]), device='cuda'))
    #
    #     return positives_torch

    def updateModel(self, cache):
        X_neg = cache['neg']
        X_pos = cache['pos']
        num_neg = len(X_neg)
        num_pos = len(X_pos)
        # X = np.vstack((X_pos, X_neg))
        # y = np.vstack((np.transpose(np.ones(num_pos)[np.newaxis]), -np.transpose(np.ones(num_neg)[np.newaxis])))
        X = torch.cat((X_pos, X_neg), 0)
        y = torch.cat((torch.transpose(torch.ones(num_pos), 0, 0), -torch.transpose(torch.ones(num_neg), 0, 0)), 0)

        # return self.classifier.train(X, y, self.classifier_options)
        if self.sigma is not None and self.lam is not None:
            print('Updating model with lambda: {} and sigma: {}'.format(self.lam, self.sigma))
            return self.classifier.train(X, y, sigma=self.sigma, lam=self.lam)
        else:
            print('Updating model with default lambda and sigma')
            return self.classifier.train(X, y)

    def trainWithMinibootstrap(self, negatives, positives):
        iterations = self.negative_selector.iterations
        caches = []
        model = []
        t = time.time()
        for i in range(self.num_classes-1):
            if (len(positives[i]) != 0) & (len(negatives[i]) != 0):
                print('---------------------- Training Class number {} ----------------------'.format(i))
                first_time = True
                for j in range(len(negatives[i])):
                    t_iter = time.time()
                    if first_time:
                        dataset = {}
                        dataset['pos'] = positives[i]
                        dataset['neg'] = negatives[i][j]
                        caches.append(dataset)
                        model.append(None)
                        first_time = False
                    else:
                        t_hard = time.time()
                        neg_pred = self.classifier.predict(model[i], negatives[i][j])  # To check
                        # hard_idx = np.argwhere(neg_pred.numpy() > self.negative_selector.neg_hard_thresh)[:,0]
                        hard_idx = torch.where(neg_pred > self.negative_selector.neg_hard_thresh)[0]
                        # caches[i]['neg'] = np.vstack((caches[i]['neg'], negatives[i][j][hard_idx]))
                        caches[i]['neg'] = torch.cat((caches[i]['neg'], negatives[i][j][hard_idx]), 0)
                        print('Hard negatives selected in {} seconds'.format(time.time() - t_hard))
                        print('Chosen {} hard negatives from the {}th batch'.format(len(hard_idx), j))

                    print('Traning with {} positives and {} negatives'.format(len(caches[i]['pos']), len(caches[i]['neg'])))
                    t_update = time.time()
                    model[i] = self.updateModel(caches[i])
                    print('Model updated in {} seconds'.format(time.time() - t_update))

                    t_easy = time.time()
                    if len(caches[i]['neg']) != 0:
                        neg_pred = self.classifier.predict(model[i], caches[i]['neg'])  # To check

                        # easy_idx = np.argwhere(neg_pred.numpy() < self.negative_selector.neg_easy_thresh)[:,0]
                        keep_idx = torch.where(neg_pred >= self.negative_selector.neg_easy_thresh)[0]
                        easy_idx = len(caches[i]['neg']) - len(keep_idx)
                        caches[i]['neg'] = caches[i]['neg'][keep_idx]
                        # caches[i]['neg'] = np.delete(caches[i]['neg'], easy_idx, axis=0)
                        print('Easy negatives selected in {} seconds'.format(time.time() - t_easy))
                        print('Removed {} easy negatives. {} Remaining'.format(easy_idx, len(caches[i]['neg'])))
                        print('Iteration {}th done in {} seconds'.format(j, time.time() - t_iter))
            else:
                model.append(None)
                dataset = {}
                caches.append(dataset)

        training_time = time.time() - t
        print('Online Classifier trained in {} seconds'.format(training_time))
        # model_name = 'model_' + self.experiment_name
        # torch.save(model, model_name)
        return model

    def trainRegionClassifier(self, opts=None):
        if opts is not None:
            self.processOptions(opts)
        print('Training Online Region Classifier')
        # Still to implement early stopping of negatives selection
        negatives = self.negative_selector.selectNegatives()
        positives = self.positive_selector.selectPositives()

        self.mean, self.std, self.mean_norm = computeFeatStatistics(positives, negatives, self.feature_folder, self.is_rpn)
        for i in range(self.num_classes-1):
            if len(positives[i]):
                positives[i] = zScores(positives[i], self.mean, self.mean_norm)
            for j in range(len(negatives[i])):
                if len(negatives[i][j]):
                    negatives[i][j] = zScores(negatives[i][j], self.mean, self.mean_norm)

        model = self.trainWithMinibootstrap(negatives, positives)

        return model

    def crossValRegionClassifier(self, dataset):
        pass

    def loadFeature(self, feat_path, img, type='mat'):
        feat_file = None
        if type == 'mat':
            file_name = img + '.mat'
            feat_file = h5py.File(os.path.join(feat_path, file_name), 'r')
        else:
            print('Unrecognized type file: {}'.format(type))

        return feat_file

    def testRegionClassifier(self, model):
        print('Online Region Classifier testing')
        with open(self.test_imset, 'r') as f:
            path_list = f.readlines()
        feat_path = os.path.join(basedir, '..', '..', '..', 'Data', 'feat_cache', self.feature_folder, 'test')

        predictions = []
        total_testing_time = 0
        for i in range(len(path_list)):
            print('Testing {}/{} : {}'.format(i, len(path_list), path_list[i].rstrip()))
            l = loadFeature(feat_path, path_list[i].rstrip())
            if l is not None:
                print('Processing image {}'.format(path_list[i]))
                I = np.nonzero(l['gt'] == 0)
                boxes = l['boxes'][I, :][0]
                X_test = torch.tensor(l['feat'][I, :][0])
                t0 = time.time()
#                if self.mean_norm != 0:
#                   X_test = zScores(X_test, self.mean, self.mean_norm)
                scores = - torch.ones((len(boxes), self.num_classes))
                for c in range(0, self.num_classes-1):
                    pred = self.classifier.predict(model[c], X_test)
                    scores[:, c+1] = torch.squeeze(pred)

                total_testing_time = total_testing_time + t0 - time.time()
                b = BoxList(torch.from_numpy(boxes), (640, 480), mode="xyxy")    # TO parametrize image shape
                # b.add_field("scores", torch.from_numpy(np.float32(scores)))
                b.add_field("scores", scores)
                b.add_field("name_file", path_list[i].rstrip())
                predictions.append(b)
            else:
                print('None feature loaded. Skipping image {}.'.format(path_list[i]))

        avg_time = total_testing_time/len(path_list)
        print('Testing an image in {} seconds.'.format(avg_time))
        return predictions

    def predict(self, dataset) -> None:
        pass
