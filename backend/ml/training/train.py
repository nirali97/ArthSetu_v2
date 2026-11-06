"""Phase 2 training on the 80/20 split. All selection uses 5-fold CV INSIDE the 80% train set; the 20% test set is
scored exactly once after the model, calibrator and threshold are frozen.

Candidates: logistic regression baseline | HistGradientBoosting | HistGradientBoosting + SMOTE (own implementation,
resampling only inside training folds) | XGBoost + imblearn-SMOTE (only if both packages import; UNTESTED here).
Selection metric: out-of-fold PR-AUC. Calibration: isotonic fitted on out-of-fold train predictions.
Usage: python3 -I backend/ml/training/train.py   (from repo root)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix, precision_recall_curve,
                             roc_auc_score)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from ml.data.schema import TARGET  # noqa: E402
from ml.explain import global_importance  # noqa: E402
from ml.features.engineering import MODEL_FEATURES  # noqa: E402
from ml.training.components import IsotonicCalibrated, SmoteModel, Winsorizer  # noqa: E402,F401

SEED = 42
HEAVY_TAIL = ["RevolvingUtilizationOfUnsecuredLines", "MonthlyIncome", "debt_ratio_valid",
              "est_monthly_obligations", "income_per_household_member"]
BINARY_IDX = [i for i, f in enumerate(MODEL_FEATURES) if f in ("income_reported", "has_90plus_delinquency", "utilization_over_limit")]
LOW_BAND_MAX = 0.05


def metrics(y, p, thr: float) -> dict:
    y = np.asarray(y)
    pred = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    div = lambda a, b: float(a / b) if b else 0.0  # noqa: E731
    prec, rec = div(tp, tp + fp), div(tp, tp + fn)
    return {"threshold": round(float(thr), 6), "accuracy": div(tp + tn, len(y)), "precision": prec, "recall": rec,
            "f1": div(2 * prec * rec, prec + rec), "roc_auc": float(roc_auc_score(y, p)),
            "pr_auc": float(average_precision_score(y, p)), "specificity": div(tn, tn + fp),
            "false_positive_rate": div(fp, fp + tn), "false_negative_rate": div(fn, fn + tp),
            "brier": float(brier_score_loss(y, p)), "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "n": int(len(y)), "positives": int(y.sum())}


def best_f1_threshold(y, p) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.clip(prec[:-1] + rec[:-1], 1e-12, None)
    return float(thr[int(np.argmax(f1))])


def threshold_for_recall(y, p, target: float) -> float:
    """Highest threshold whose recall is >= target (keeps precision as high as possible for that recall). Train/OOF data only."""
    prec, rec, thr = precision_recall_curve(y, p)
    ok = np.flatnonzero(rec[:-1] >= target)
    if len(ok) == 0:
        raise ValueError(f"recall target {target} unreachable")
    return float(thr[ok[-1]])


def load_split(d: Path, name: str):
    df = pd.read_csv(d / f"{name}.csv", index_col=0)
    return df[MODEL_FEATURES], df[TARGET].astype(int)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-recall", type=float, default=0.0, help="e.g. 0.70: pick the threshold that reaches this recall on train CV (precision drops); 0 = max-F1")
    args = ap.parse_args()
    ddir = sorted((ROOT / "data" / "processed").glob("gmsc-v1-*-split8020"))[-1]
    manifest = json.loads((ddir / "manifest.json").read_text())
    Xtr, ytr = load_split(ddir, "train")
    Xte, yte = load_split(ddir, "test")
    cv = StratifiedKFold(5, shuffle=True, random_state=SEED)

    # Tune boosting hyper-parameters by CV on train only
    grid = GridSearchCV(
        HistGradientBoostingClassifier(max_iter=300, early_stopping=True, validation_fraction=0.1, n_iter_no_change=20, random_state=SEED),
        {"learning_rate": [0.05, 0.1], "max_depth": [3, 5], "min_samples_leaf": [20, 100], "l2_regularization": [0.0, 1.0]},
        scoring="average_precision", cv=StratifiedKFold(3, shuffle=True, random_state=SEED), n_jobs=-1).fit(Xtr, ytr)
    hgb = grid.best_estimator_

    cands = {
        "logistic_regression_baseline": Pipeline([("clip", Winsorizer(HEAVY_TAIL)), ("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler()),
                                                  ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED))]),
        "hist_gradient_boosting": hgb,
        "hist_gradient_boosting_smote": SmoteModel(clf=hgb, sampling_strategy=0.5, binary_idx=BINARY_IDX, seed=SEED),
    }
    xgb_status = "not_installed"
    try:  # UNTESTED in the build environment (packages unavailable). Activates automatically when installed.
        from imblearn.over_sampling import SMOTE
        from imblearn.pipeline import Pipeline as ImbPipeline
        from xgboost import XGBClassifier
        cands["xgboost_smote"] = ImbPipeline([("imp", SimpleImputer(strategy="median")), ("smote", SMOTE(sampling_strategy=0.5, random_state=SEED)),
                                              ("clf", XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                                                                    colsample_bytree=0.8, eval_metric="aucpr", random_state=SEED, n_jobs=-1))])
        xgb_status = "available_untested"
    except ImportError:
        pass

    oof, cv_summary = {}, {}
    for name, est in cands.items():
        oof[name] = cross_val_predict(est, Xtr, ytr, cv=cv, method="predict_proba", n_jobs=1)[:, 1]  # SMOTE happens inside each fold's fit
        cv_summary[name] = {"oof_roc_auc": float(roc_auc_score(ytr, oof[name])), "oof_pr_auc": float(average_precision_score(ytr, oof[name]))}
        print(name, cv_summary[name], flush=True)

    chosen = max(cv_summary, key=lambda k: cv_summary[k]["oof_pr_auc"])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[chosen], ytr)  # train-only OOF
    oof_cal = iso.predict(oof[chosen])
    thr = threshold_for_recall(ytr, oof_cal, args.target_recall) if args.target_recall else best_f1_threshold(ytr, oof_cal)
    rule = f"recall >= {args.target_recall} on calibrated out-of-fold train predictions" if args.target_recall else "maximise F1 on calibrated out-of-fold train predictions"
    final = IsotonicCalibrated(cands[chosen].fit(Xtr, ytr), iso)

    p_test = final.predict_proba(Xte)[:, 1]  # test scored once
    p_train = final.predict_proba(Xtr)[:, 1]
    dfp = pd.DataFrame({"p": p_test, "y": yte.to_numpy()})
    dfp["bin"] = pd.qcut(dfp.p, 10, duplicates="drop")
    reliability = [{"mean_predicted": float(g.p.mean()), "observed_rate": float(g.y.mean()), "n": int(len(g))}
                   for _, g in dfp.groupby("bin", observed=True)]

    rng = np.random.default_rng(SEED)
    background = Xtr.iloc[rng.choice(len(Xtr), 25, replace=False)].reset_index(drop=True)
    sample = Xtr.iloc[rng.choice(len(Xtr), 120, replace=False)].reset_index(drop=True)
    importance = global_importance(lambda df: final.predict_proba(df)[:, 1], sample, background)

    version = f"model-{ddir.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    out = ROOT / "models"
    out.mkdir(exist_ok=True)
    bands = {"low_max": LOW_BAND_MAX, "high_min": round(thr, 4)}
    joblib.dump({"model": final, "features": MODEL_FEATURES, "threshold": thr, "bands": bands, "background": background, "version": version}, out / f"{version}.joblib")
    results = {"selected_model": chosen, "cv_5fold_train_oof": cv_summary, "cv_oof_calibrated_at_threshold": metrics(ytr, oof_cal, thr),
               "train_in_sample": metrics(ytr, p_train, thr), "test": metrics(yte, p_test, thr), "gb_best_params": grid.best_params_,
               "reliability_test_deciles": reliability, "global_importance": importance, "base_rate_train": float(ytr.mean()),
               "decision_threshold_rule": rule, "risk_bands": bands}
    meta = {"model_version": version, "dataset_version": manifest["dataset_version"], "trained_utc": datetime.now(timezone.utc).isoformat(),
            "random_seed": SEED, "split_policy": manifest["split_policy"], "xgboost_smote_status": xgb_status,
            "library_versions": {"scikit_learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__},
            "features": MODEL_FEATURES, "algorithm": chosen, "resampling": "own SMOTE inside CV folds" if "smote" in chosen else "none", **results}
    (out / f"{version}.json").write_text(json.dumps(meta, indent=2))
    for s in ["cv_oof_calibrated_at_threshold", "train_in_sample", "test"]:
        m = results[s]
        print(f"{s:32s} thr={m['threshold']:.3f} AUC={m['roc_auc']:.4f} PR={m['pr_auc']:.4f} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} Acc={m['accuracy']:.3f} Brier={m['brier']:.4f} {m['confusion_matrix']}")
    print("selected:", chosen, "| top features:", [r["feature"] for r in importance[:5]])


if __name__ == "__main__":
    main()
