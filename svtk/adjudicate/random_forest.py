#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright © 2017 Matthew Stone <mstone5@mgh.harvard.edu>
# Distributed under terms of the MIT license.

"""

"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import roc_curve


def rf_classify(metrics, trainable, testable, features, labeler, cutoffs, name,
                clean_cutoffs=False):
    """Wrapper to run random forest and assign probabilities"""
    rf = RandomForest(trainable, testable, features, cutoffs, labeler,
                      clean_cutoffs)
    rf.run()
    metrics.loc[rf.testable.index, name] = rf.probs

    return metrics, rf.cutoffs


class RandomForest:
    def __init__(self, trainable, testable, features, cutoffs, labeler,
                 clean_cutoffs=False):
        def has_null_features(df):
            return df[features].isnull().any(axis=1)

        self.clean = trainable.loc[~has_null_features(trainable)].copy()
        if self.clean.shape[0] == 0:
            raise Exception('No clean variants found')

        self.testable = testable.loc[~has_null_features(testable)].copy()

        self.features = features

        self.labeler = labeler
        self.encoder = LabelEncoder().fit(['Fail', 'Pass'])

        self.clean_cutoffs = clean_cutoffs
        self.cutoff_features = cutoffs
        self.cutoffs = None

    def run(self):
        self.label_training_data()
        self.select_training_data()
        self.learn_probs()
        self.learn_cutoffs()
        self.cutoff_probs()

    def label_training_data(self):
        self.clean['label'] = self.labeler.label(self.clean)

    def select_training_data(self):
        self.train = self.clean.loc[self.clean.label != 'Unlabeled'].copy()

    def learn_probs(self):
        X_train = self.train[self.features].as_matrix()

        y_train = self.encoder.transform(self.train.label)

        self.rf = RandomForestClassifier(n_estimators=500, random_state=343124,
                                         oob_score=True, max_features=None)

        self.rf.fit(X_train, y_train)

        X = self.testable[self.features].as_matrix()
        probs = self.rf.predict_proba(X)

        self.probs = probs[:, 1]

    def learn_cutoffs(self):
        cutoffs = {}
        # Restrict learning cutoffs to "clean" variants
        if self.clean_cutoffs:
            cutoff_metrics = self.clean
        else:
            cutoff_metrics = self.testable

        cutoff_metrics['pass_cutoffs'] = True
        passing = cutoff_metrics['pass_cutoffs']

        for feature in self.cutoff_features['indep']:
            metric = cutoff_metrics[feature]
            idx = np.searchsorted(self.testable.index, cutoff_metrics.index)
            cutoff = learn_cutoff(metric, self.probs[idx])

            cutoffs[feature] = cutoff
            passing = passing & (cutoff_metrics[feature] >= cutoff)

        passing = cutoff_metrics.loc[passing]
        for feature in self.cutoff_features['dep']:
            metric = passing[feature]
            # Subset probabilities to those in passing set
            idx = np.searchsorted(self.testable.index, passing.index)
            cutoffs[feature] = learn_cutoff(metric, self.probs[idx])

        self.cutoffs = pd.DataFrame.from_dict({'cutoff': cutoffs},
                                              orient='columns')\
                                   .reset_index()
        self.cutoffs = self.cutoffs.rename(columns=dict(index='metric'))

    def cutoff_probs(self):
        self.testable['prob'] = self.probs
        passes = self.testable.prob >= 0.5

        # If metrics are below the observed cutoff, force failure
        for idx, row in self.cutoffs.iterrows():
            metric, cutoff = row['metric'], row['cutoff']
            self.testable.loc[passes & (self.testable[metric] < cutoff), 'prob'] = 0.499

        self.probs = self.testable.prob.as_matrix()

def learn_cutoff(metric, probs):
    preds = metric.as_matrix()

    # Pass/fail if greater/less than 0.5
    classify = np.vectorize(lambda x: 1 if x >= 0.5 else 0)
    truth = classify(probs)

    fpr, tpr, thresh = roc_curve(truth, preds)
    dist = np.sqrt((fpr - 0) ** 2 + (tpr - 1) ** 2)
    best_idx = np.argmin(dist)

    return thresh[best_idx]
