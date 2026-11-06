import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from ml.explain import shapley  # noqa: E402
from ml.features.engineering import MODEL_FEATURES, engineer_features  # noqa: E402
from ml.training.components import SmoteModel, Winsorizer, smote_resample  # noqa: E402
from ml.training.train import best_f1_threshold, metrics, threshold_for_recall  # noqa: E402

MODELS = sorted((ROOT / "models").glob("model-*.joblib"))
needs_model = pytest.mark.skipif(not MODELS, reason="no trained model artifact")


def _art():
    return joblib.load(MODELS[-1])


def _meta():
    return json.loads(MODELS[-1].with_suffix(".json").read_text())


def test_smote_only_adds_minority_and_keeps_originals():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 4)); y = np.zeros(500, int); y[:25] = 1
    Xr, yr = smote_resample(X, y, 0.5, binary_idx=[3], seed=1)
    assert np.array_equal(Xr[:500], X) and (yr[:500] == y).all()           # originals untouched
    assert (yr[500:] == 1).all() and yr.sum() == int(0.5 * 475)             # minority raised to 50% of majority
    assert set(np.unique(Xr[500:, 3])) <= set(np.round(np.unique(Xr[500:, 3])))  # binary column rounded
    lo, hi = X[y == 1].min(0), X[y == 1].max(0)
    assert (Xr[500:, :3] >= lo[:3] - 1e-9).all() and (Xr[500:, :3] <= hi[:3] + 1e-9).all()  # interpolation stays in minority hull


def test_resampling_boundary_prediction_never_resamples():
    from sklearn.ensemble import HistGradientBoostingClassifier
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 3)); y = (X[:, 0] + rng.normal(size=400) > 1.5).astype(int)
    m = SmoteModel(HistGradientBoostingClassifier(max_iter=20), 0.6).fit(X, y)
    a = m.predict_proba(X[:10]); b = m.predict_proba(X[:10])
    assert a.shape == (10, 2) and np.array_equal(a, b)


def test_winsorizer_fits_on_train_only():
    w = Winsorizer(["a"], 0.9).fit(pd.DataFrame({"a": np.arange(100.0)}))
    assert w.transform(pd.DataFrame({"a": [1e9]}))["a"].iloc[0] == w.caps_["a"]


def test_metrics_known_values():
    m = metrics(pd.Series([0, 0, 1, 1]), np.array([0.1, 0.6, 0.4, 0.9]), 0.5)
    assert m["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1} and m["accuracy"] == 0.5 and m["false_negative_rate"] == 0.5
    assert 0 < best_f1_threshold(pd.Series([0, 0, 1, 1]), np.array([0.1, 0.6, 0.4, 0.9])) <= 0.9


@needs_model
def test_artifact_and_metadata_complete():
    a, meta = _art(), _meta()
    assert a["features"] == MODEL_FEATURES and "split8020" in meta["dataset_version"] + meta["split_policy"].replace("/", "").replace(" ", "") or "80/20" in meta["split_policy"]
    for k in ["model_version", "dataset_version", "random_seed", "trained_utc", "test", "train_in_sample", "cv_5fold_train_oof", "global_importance"]:
        assert k in meta
    assert meta["test"]["n"] != meta["train_in_sample"]["n"]
    assert meta["test"]["n"] / (meta["test"]["n"] + meta["train_in_sample"]["n"]) == pytest.approx(0.2, abs=0.001)


@needs_model
def test_inference_path_handles_missing_and_is_deterministic():
    raw = pd.DataFrame([{"RevolvingUtilizationOfUnsecuredLines": 0.3, "age": 40, "NumberOfTime30-59DaysPastDueNotWorse": 0, "DebtRatio": 0.4,
                         "MonthlyIncome": np.nan, "NumberOfOpenCreditLinesAndLoans": 5, "NumberOfTimes90DaysLate": 0,
                         "NumberRealEstateLoansOrLines": 1, "NumberOfTime60-89DaysPastDueNotWorse": 0, "NumberOfDependents": np.nan}])
    X = engineer_features(raw)
    p = _art()["model"].predict_proba(X)[:, 1]
    assert list(X.columns) == MODEL_FEATURES and 0 <= p[0] <= 1 and p[0] == _art()["model"].predict_proba(X)[:, 1][0]


@needs_model
def test_shapley_is_exactly_additive_and_uses_deployed_model():
    a = _art()
    f = lambda df: a["model"].predict_proba(df)[:, 1]  # noqa: E731
    x = a["background"].iloc[[3]]
    r = shapley(f, x, a["background"], n_perm=20, seed=1)
    assert r["prediction"] == pytest.approx(f(x)[0], abs=1e-12)
    assert sum(r["contributions"].values()) == pytest.approx(r["prediction"] - r["base_value"], abs=1e-9)
    assert list(r["contributions"]) == MODEL_FEATURES


@needs_model
def test_shapley_irrelevant_feature_gets_zero():
    a = _art()
    f = lambda df: df["age"].to_numpy() / 100.0  # synthetic model depending only on age  # noqa: E731
    x = a["background"].iloc[[0]].copy(); x["age"] = 90.0
    r = shapley(f, x, a["background"], n_perm=10, seed=0)
    assert all(abs(v) < 1e-12 for k, v in r["contributions"].items() if k != "age") and r["contributions"]["age"] > 0


def test_threshold_for_recall_meets_target_and_is_highest():
    rng = np.random.default_rng(0)
    y = (rng.random(5000) < 0.1).astype(int)
    p = np.clip(0.1 + 0.5 * (y - 0.1) + rng.normal(0, 0.15, 5000), 0, 1)
    for target in (0.5, 0.7, 0.9):
        thr = threshold_for_recall(y, p, target)
        rec = ((p >= thr) & (y == 1)).sum() / y.sum()
        assert rec >= target
        assert ((p >= thr + 1e-6) & (y == 1)).sum() / y.sum() < target + 0.02   # not needlessly low
