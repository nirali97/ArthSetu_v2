"""Shapley-value attributions for one applicant (permutation-sampling estimator, interventional baseline).

NOT the `shap` library: it is unavailable in this environment. It estimates the same quantity (Shapley values of the
model's probability output w.r.t. a background sample) and is exactly additive:
    prediction - mean(background prediction) == sum(contributions)
Because every sampled permutation telescopes, additivity holds exactly; only the split between features is estimated
(standard error returned). Uses the deployed model itself, same feature order, real feature values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def shapley(predict, x: pd.DataFrame, background: pd.DataFrame, n_perm: int = 60, seed: int = 0) -> dict:
    cols = list(x.columns)
    d, m = len(cols), len(background)
    rng = np.random.default_rng(seed)
    xv = x.to_numpy(float)[0]
    bg = background[cols].to_numpy(float)
    perms = np.argsort(rng.random((n_perm, d)), axis=1)             # perms[p, step] = column added at that step
    rank = np.argsort(perms, axis=1)                                 # rank[p, col] = step at which col is added
    steps = np.arange(d + 1)[None, :, None]                          # hybrid k has columns with rank < k from x
    mask = rank[:, None, :] < steps                                  # (n_perm, d+1, d)
    hybrid = np.where(mask[:, :, None, :], xv[None, None, None, :], bg[None, None, :, :])  # (P, d+1, m, d)
    f = predict(pd.DataFrame(hybrid.reshape(-1, d), columns=cols)).reshape(n_perm, d + 1, m)
    delta = (f[:, 1:, :] - f[:, :-1, :]).mean(axis=2)                # (P, d): marginal gain at each step
    per_perm = np.zeros((n_perm, d))
    np.put_along_axis(per_perm, perms, delta, axis=1)                # re-index step -> column
    contrib = per_perm.mean(axis=0)
    se = per_perm.std(axis=0, ddof=1) / np.sqrt(n_perm)
    return {"base_value": float(f[:, 0, :].mean()), "prediction": float(f[:, d, :].mean()),
            "contributions": {c: float(v) for c, v in zip(cols, contrib)},
            "std_error": {c: float(v) for c, v in zip(cols, se)}}


def global_importance(predict, X: pd.DataFrame, background: pd.DataFrame, n_perm: int = 30, seed: int = 0) -> list[dict]:
    rows = []
    for i in range(len(X)):
        rows.append(shapley(predict, X.iloc[[i]], background, n_perm, seed + i)["contributions"])
    C = pd.DataFrame(rows)
    out = [{"feature": c, "mean_abs": float(C[c].abs().mean()), "mean_signed": float(C[c].mean())} for c in C.columns]
    return sorted(out, key=lambda r: -r["mean_abs"])
