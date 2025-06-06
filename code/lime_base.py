"""
Contains abstract functionality for learning locally linear sparse model.
"""
import numpy as np
import scipy as sp
import sklearn
from sklearn.linear_model import Ridge
from slime_lm._least_angle import lars_path
from sklearn.utils import check_random_state
from scipy.stats import entropy     #Khoa add
from scipy.spatial.distance import hamming  #Khoa add
import random   #Khoa add


class LimeBase(object):
    """Class for learning a locally linear sparse model from perturbed data"""
    def __init__(self,
                 kernel_fn,
                 verbose=False,
                 random_state=None):
        """Init function

        Args:
            kernel_fn: function that transforms an array of distances into an
                        array of proximity values (floats).
            verbose: if true, print local prediction values from linear model.
            random_state: an integer or numpy.RandomState that will be used to
                generate random numbers. If None, the random state will be
                initialized using the internal numpy seed.
        """
        self.kernel_fn = kernel_fn
        self.verbose = verbose
        self.random_state = check_random_state(random_state)

    @staticmethod
    def generate_lars_path(weighted_data, weighted_labels, testing=False, alpha=0.05):
        """Generates the lars path for weighted data.

        Args:
            weighted_data: data that has been weighted by kernel
            weighted_label: labels, weighted by kernel

        Returns:
            (alphas, coefs), both are arrays corresponding to the
            regularization parameter and coefficients, respectively
        """
        x_vector = weighted_data
        if not testing:
            alphas, _, coefs = lars_path(x_vector,
                                         weighted_labels,
                                         method='lasso',
                                         verbose=False,
                                         alpha=alpha)
            return alphas, coefs
        else:
            alphas, _, coefs, test_result = lars_path(x_vector,
                                                           weighted_labels,
                                                           method='lasso',
                                                           verbose=False,
                                                           testing=testing)
            return alphas, coefs, test_result   

    def forward_selection(self, data, labels, weights, num_features):
        """Iteratively adds features to the model"""
        clf = Ridge(alpha=0, fit_intercept=True, random_state=self.random_state)
        used_features = []
        for _ in range(min(num_features, data.shape[1])):
            max_ = -100000000
            best = 0
            for feature in range(data.shape[1]):
                if feature in used_features:
                    continue
                clf.fit(data[:, used_features + [feature]], labels,
                        sample_weight=weights)
                score = clf.score(data[:, used_features + [feature]],
                                  labels,
                                  sample_weight=weights)
                if score > max_:
                    best = feature
                    max_ = score
            used_features.append(best)
        return np.array(used_features)

    def feature_selection(self, data, labels, weights, num_features, method, testing=False, alpha=0.05, use_stratification=True):
        """Selects features for the model. see explain_instance_with_data to
           understand the parameters."""
        if method == 'none':
            return np.array(range(data.shape[1]))
        elif method == 'forward_selection':
            return self.forward_selection(data, labels, weights, num_features)
        elif method == 'highest_weights':
            clf = Ridge(alpha=0.01, fit_intercept=True,
                        random_state=self.random_state)
            clf.fit(data, labels, sample_weight=weights)

            coef = clf.coef_
            if sp.sparse.issparse(data):
                coef = sp.sparse.csr_matrix(clf.coef_)
                weighted_data = coef.multiply(data[0])
                # Note: most efficient to slice the data before reversing
                sdata = len(weighted_data.data)
                argsort_data = np.abs(weighted_data.data).argsort()
                # Edge case where data is more sparse than requested number of feature importances
                # In that case, we just pad with zero-valued features
                if sdata < num_features:
                    nnz_indexes = argsort_data[::-1]
                    indices = weighted_data.indices[nnz_indexes]
                    num_to_pad = num_features - sdata
                    indices = np.concatenate((indices, np.zeros(num_to_pad, dtype=indices.dtype)))
                    indices_set = set(indices)
                    pad_counter = 0
                    for i in range(data.shape[1]):
                        if i not in indices_set:
                            indices[pad_counter + sdata] = i
                            pad_counter += 1
                            if pad_counter >= num_to_pad:
                                break
                else:
                    nnz_indexes = argsort_data[sdata - num_features:sdata][::-1]
                    indices = weighted_data.indices[nnz_indexes]
                return indices
            else:
                weighted_data = coef * data[0]
                feature_weights = sorted(
                    zip(range(data.shape[1]), weighted_data),
                    key=lambda x: np.abs(x[1]),
                    reverse=True)
                return np.array([x[0] for x in feature_weights[:num_features]])
        elif method == 'lasso_path':
            if not testing:
                weighted_data = ((data - np.average(data, axis=0, weights=weights))
                                 * np.sqrt(weights[:, np.newaxis]))
                weighted_labels = ((labels - np.average(labels, weights=weights))
                                   * np.sqrt(weights))

                nonzero = range(weighted_data.shape[1])
                _, coefs = self.generate_lars_path(weighted_data,
                                                   weighted_labels)
                for i in range(len(coefs.T) - 1, 0, -1):
                    nonzero = coefs.T[i].nonzero()[0]
                    if len(nonzero) <= num_features:
                        break
                used_features = nonzero
                return used_features
            else:
                weighted_data = ((data - np.average(data, axis=0, weights=weights))
                                 * np.sqrt(weights[:, np.newaxis]))
                weighted_labels = ((labels - np.average(labels, weights=weights))
                                   * np.sqrt(weights))
                # Xscaler = sklearn.preprocessing.StandardScaler()
                # Xscaler.fit(weighted_data)
                # weighted_data = Xscaler.transform(weighted_data)
             
                # Yscaler = sklearn.preprocessing.StandardScaler()
                # Yscaler.fit(weighted_labels.reshape(-1, 1))
                # weighted_labels = Yscaler.transform(weighted_labels.reshape(-1, 1)).ravel()

                nonzero = range(weighted_data.shape[1])
                alphas, coefs, test_result = self.generate_lars_path(weighted_data,
                                                                     weighted_labels, 
                                                                     testing=True,
                                                                     alpha=alpha)
                for i in range(len(coefs.T) - 1, 0, -1):
                    nonzero = coefs.T[i].nonzero()[0]
                    if use_stratification:
                        break
                    if len(nonzero) <= num_features:
                        break
                used_features = nonzero
                return used_features, test_result
        elif method == 'auto':
            if num_features <= 6:
                n_method = 'forward_selection'
            else:
                n_method = 'highest_weights'
            return self.feature_selection(data, labels, weights,
                                          num_features, n_method)

    def explain_instance_with_data(self,
                                   neighborhood_data,
                                   neighborhood_labels,
                                   distances,
                                   label,
                                   num_features,
                                   feature_selection='auto',
                                   model_regressor=None):
        """Takes perturbed data, labels and distances, returns explanation.

        Args:
            neighborhood_data: perturbed data, 2d array. first element is
                               assumed to be the original data point.
            neighborhood_labels: corresponding perturbed labels. should have as
                                 many columns as the number of possible labels.
            distances: distances to original data point.
            label: label for which we want an explanation
            num_features: maximum number of features in explanation
            feature_selection: how to select num_features. options are:
                'forward_selection': iteratively add features to the model.
                    This is costly when num_features is high
                'highest_weights': selects the features that have the highest
                    product of absolute weight * original data point when
                    learning with all the features
                'lasso_path': chooses features based on the lasso
                    regularization path
                'none': uses all features, ignores num_features
                'auto': uses forward_selection if num_features <= 6, and
                    'highest_weights' otherwise.
            model_regressor: sklearn regressor to use in explanation.
                Defaults to Ridge regression if None. Must have
                model_regressor.coef_ and 'sample_weight' as a parameter
                to model_regressor.fit()

        Returns:
            (intercept, exp, score, local_pred):
            intercept is a float.
            exp is a sorted list of tuples, where each tuple (x,y) corresponds
            to the feature id (x) and the local weight (y). The list is sorted
            by decreasing absolute value of y.
            score is the R^2 value of the returned explanation
            local_pred is the prediction of the explanation model on the original instance
        """

        weights = self.kernel_fn(distances)
        labels_column = neighborhood_labels[:, label]
        used_features = self.feature_selection(neighborhood_data,
                                               labels_column,
                                               weights,
                                               num_features,
                                               feature_selection)
        if model_regressor is None:
            model_regressor = Ridge(alpha=1, fit_intercept=True,
                                    random_state=self.random_state)
        easy_model = model_regressor
        easy_model.fit(neighborhood_data[:, used_features],
                       labels_column, sample_weight=weights)
        prediction_score = easy_model.score(
            neighborhood_data[:, used_features],
            labels_column, sample_weight=weights)

        local_pred = easy_model.predict(neighborhood_data[0, used_features].reshape(1, -1))

        if self.verbose:
            print('Intercept', easy_model.intercept_)
            print('Prediction_local', local_pred,)
            print('Right:', neighborhood_labels[0, label])
        return (easy_model.intercept_,
                sorted(zip(used_features, easy_model.coef_),
                       key=lambda x: np.abs(x[1]), reverse=True),
                prediction_score, local_pred)

    def testing_explain_instance_with_data(self,
                                   neighborhood_data,
                                   neighborhood_labels,
                                   distances,
                                   label,
                                   num_features,
                                   feature_selection='lasso_path',
                                   weight_adjustments=None,
                                   model_regressor=None,
                                   use_stratification=True,
                                   alpha=0.05):
        """Takes perturbed data, labels and distances, returns explanation. 
            This is a helper function for slime.

        Args:
            neighborhood_data: perturbed data, 2d array. first element is
                               assumed to be the original data point.
            neighborhood_labels: corresponding perturbed labels. should have as
                                 many columns as the number of possible labels.
            distances: distances to original data point.
            label: label for which we want an explanation
            num_features: maximum number of features in explanation
            feature_selection: how to select num_features. options are:
                'forward_selection': iteratively add features to the model.
                    This is costly when num_features is high
                'highest_weights': selects the features that have the highest
                    product of absolute weight * original data point when
                    learning with all the features
                'lasso_path': chooses features based on the lasso
                    regularization path
                'none': uses all features, ignores num_features
                'auto': uses forward_selection if num_features <= 6, and
                    'highest_weights' otherwise.
            model_regressor: sklearn regressor to use in explanation.
                Defaults to Ridge regression if None. Must have
                model_regressor.coef_ and 'sample_weight' as a parameter
                to model_regressor.fit()
            alpha: significance level of hypothesis testing.

        Returns:
            (intercept, exp, score, local_pred):
            intercept is a float.
            exp is a sorted list of tuples, where each tuple (x,y) corresponds
            to the feature id (x) and the local weight (y). The list is sorted
            by decreasing absolute value of y.
            score is the R^2 value of the returned explanation
            local_pred is the prediction of the explanation model on the original instance
        """
        if weight_adjustments is not None:
            distances *= weight_adjustments
        weights = self.kernel_fn(distances)
        labels_column = neighborhood_labels[:, label]
        if model_regressor is None:
            model_regressor = Ridge(alpha=1, fit_intercept=True,
                                    random_state=self.random_state)
        
        elimination=[]
        if use_stratification:
            elimination = self.fit_ridge_on_k_neighbors(neighborhood_data, labels_column)
        used_features, test_result = self.feature_selection(neighborhood_data,
                                                                    labels_column,
                                                                    weights,
                                                                    num_features,
                                                                    feature_selection,
                                                                    testing=True,
                                                                    alpha=alpha,
                                                                    use_stratification=use_stratification)
        #print("used_features 1:")
        #print(len(used_features))
        used_features = list(set(used_features)-set(elimination))
        #print("used_features 2:")
        #print(len(used_features))
        easy_model = model_regressor
        easy_model.fit(neighborhood_data[:, used_features],
                       labels_column, sample_weight=weights)
        prediction_score = easy_model.score(
            neighborhood_data[:, used_features],
            labels_column, sample_weight=weights)

        local_pred = easy_model.predict(neighborhood_data[0, used_features].reshape(1, -1))

        if self.verbose:
            print('Intercept', easy_model.intercept_)
            print('Prediction_local', local_pred,)
            print('Right:', neighborhood_labels[0, label])
        return (easy_model.intercept_,
                sorted(zip(used_features, easy_model.coef_),
                       key=lambda x: np.abs(x[1]), reverse=True),
                prediction_score, local_pred, used_features, test_result)

    def fit_ridge_on_k_neighbors(self, neighborhood_data, labels_column):
        n_samples = neighborhood_data.shape[0]
        coefs = np.zeros((n_samples, neighborhood_data.shape[1]))
        iter = 0
        flags = np.ones(neighborhood_data.shape[1], dtype = bool)
        elimination = []
        while iter < 5:
            feats = [i for i in range(neighborhood_data.shape[1]) if flags[i]]
            coefs = np.zeros((n_samples, len(feats)), dtype=float)
            for i in range(n_samples):
                model_regressor = Ridge(alpha=1, fit_intercept=True, random_state=self.random_state)
                boots_sample_idx = np.random.choice(list(range(n_samples)), size = n_samples, replace = True)
                # Dữ liệu lân cận
                X_neighbors = neighborhood_data[boots_sample_idx]
                X_neighbors = X_neighbors[:,feats]
                y_neighbors = labels_column[boots_sample_idx]
                # Huấn luyện Ridge với k mẫu lân cận
                model_regressor.fit(X_neighbors, y_neighbors)
                # Lưu hệ số hồi quy cho mẫu thứ i
                coefs[i, :] = model_regressor.coef_
            idx = 0
            for i in feats:
                signs = np.sign(coefs[:,idx])
                unique, counts = np.unique(signs, return_counts=True)
                probabilities = counts / len(signs)
                sign_entropy = entropy(probabilities, base=2)     #log2(prob)
                if sign_entropy > 0.85:      #set threshold to eliminate unstable features
                    elimination.append(feats[idx])
                    flags[feats[idx]] = 0
                idx += 1
            iter = iter + 1
        return elimination

