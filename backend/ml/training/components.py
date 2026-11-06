"""Picklable model components (must live in an importable module, never in __main__)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin, clone
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.neighbors import NearestNeighbors


class Winsorizer(BaseEstimator, TransformerMixin):
    """Clip chosen columns at a train-fitted upper quantile (DataFrame in, DataFrame out)."""

    def __init__(self, cols=None, q: float = 0.99):
        self.cols, self.q = cols, q

    def fit(self, X, y=None):
        self.caps_ = {c: float(X[c].quantile(self.q)) for c in (self.cols or [])}
        return self

    def transform(self, X):
        X = X.copy()
        for c, cap in self.caps_.items():
            X[c] = X[c].clip(upper=cap)
        return X


def smote_resample(X: np.ndarray, y: np.ndarray, sampling_strategy: float = 0.5, k: int = 5,
                   binary_idx=(), seed: int = 42):
    """SMOTE (Chawla et al. 2002). Oversamples the minority class to `sampling_strategy` x majority count.

    Neighbours are found in standardised space; synthetic points interpolate between a minority sample and one of
    its k nearest minority neighbours. Binary columns are rounded afterwards (a pragmatic SMOTE-NC-like step).
    Call ONLY on training data; X must be complete (imputed)."""
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(y == 1)
    n_new = int(sampling_strategy * (y == 0).sum()) - len(pos)
    if n_new <= 0 or len(pos) <= k:
        return X, y
    Xp = X[pos]
    sd = Xp.std(axis=0)
    sd[sd == 0] = 1.0
    nn = NearestNeighbors(n_neighbors=k + 1).fit(Xp / sd)
    neigh = nn.kneighbors(Xp / sd, return_distance=False)[:, 1:]
    base = rng.integers(len(pos), size=n_new)
    other = neigh[base, rng.integers(k, size=n_new)]
    gap = rng.random((n_new, 1))
    Xn = Xp[base] + gap * (Xp[other] - Xp[base])
    for j in binary_idx:
        Xn[:, j] = np.round(Xn[:, j])
    return np.vstack([X, Xn]), np.concatenate([y, np.ones(n_new, dtype=y.dtype)])


class SmoteModel(BaseEstimator, ClassifierMixin):
    """median-impute -> SMOTE (fit only) -> classifier. Prediction never resamples."""

    def __init__(self, clf=None, sampling_strategy: float = 0.5, k: int = 5, binary_idx=(), seed: int = 42):
        self.clf, self.sampling_strategy, self.k, self.binary_idx, self.seed = clf, sampling_strategy, k, binary_idx, seed

    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y)
        self.imp_ = SimpleImputer(strategy="median").fit(X)
        Xr, yr = smote_resample(self.imp_.transform(X), y, self.sampling_strategy, self.k, self.binary_idx, self.seed)
        self.clf_ = clone(self.clf).fit(Xr, yr)
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, X):
        return self.clf_.predict_proba(self.imp_.transform(np.asarray(X, float)))

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


class IsotonicCalibrated:
    """Final deployable model: base model + isotonic map fitted on out-of-fold TRAIN predictions."""

    def __init__(self, model, iso: IsotonicRegression):
        self.model, self.iso = model, iso

    def predict_proba(self, X):
        raw = self.model.predict_proba(X)[:, 1]
        p = np.clip(self.iso.predict(raw), 0.0, 1.0)
        return np.column_stack([1 - p, p])
