"""XGBoost training for ArthSetu (run this yourself; needs: pip install xgboost imbalanced-learn).

    python3 -I backend/ml/training/train_xgboost.py                 # full run (~10-25 min on a laptop)
    python3 -I backend/ml/training/train_xgboost.py --n-iter 40     # wider search, usually a little better

Protocol (no leakage):
  * Uses the 80/20 split from scripts/run_phase1.py. The 20% TEST set is scored exactly once, at the end.
  * Hyper-parameters are searched with 3-fold CV INSIDE the 80% train set; candidates are then compared by 5-fold
    out-of-fold PR-AUC on train.
  * SMOTENC lives inside an imblearn Pipeline, so synthetic samples are created ONLY from each fold's training part,
    never from validation folds, never from the test set. Prediction never resamples.
  * Probabilities are calibrated with isotonic regression fitted on out-of-fold train predictions; the decision threshold
    (max F1) is also chosen on those. Nothing is tuned on the test set.
Candidates: XGBoost plain | XGBoost + scale_pos_weight | XGBoost + SMOTENC.
Output: a model artifact + metadata JSON in models/ in the exact format the web app loads (restart the server to use it).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, cross_val_predict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
try:
    import xgboost
    from imblearn.over_sampling import SMOTENC
    from imblearn.pipeline import Pipeline as ImbPipeline
    from xgboost import XGBClassifier
except ImportError as e:
    sys.exit(f"Could not import xgboost / imbalanced-learn: {e!r}\n"
             "If a package is missing: pip install xgboost imbalanced-learn\n"
             "If it is installed but fails inside sklearn, the versions are incompatible (old imbalanced-learn + new scikit-learn).\n"
             "Fix: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-pinned.txt")

from ml.explain import global_importance  # noqa: E402
from ml.features.engineering import MODEL_FEATURES  # noqa: E402
from ml.training.components import IsotonicCalibrated  # noqa: E402
from ml.training.train import BINARY_IDX, LOW_BAND_MAX, best_f1_threshold, load_split, metrics, threshold_for_recall  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)

SPACE = {"n_estimators": [200, 300, 500, 800], "learning_rate": [0.02, 0.03, 0.05, 0.08], "max_depth": [2, 3, 4, 5, 6],
         "min_child_weight": [1, 3, 5, 10, 20], "subsample": [0.6, 0.8, 1.0], "colsample_bytree": [0.5, 0.7, 0.9, 1.0],
         "reg_lambda": [1, 3, 10, 30], "reg_alpha": [0, 0.1, 1], "gamma": [0, 0.5, 1, 3]}


def build_candidates(seed: int, jobs: int):
    def xgb(**kw):
        return XGBClassifier(tree_method="hist", n_jobs=jobs, random_state=seed, eval_metric="aucpr", **kw)
    pre = lambda p: {p + k: v for k, v in SPACE.items()}  # noqa: E731
    return {
        "xgboost": (xgb(), dict(SPACE)),
        "xgboost_scale_pos_weight": (xgb(), {**SPACE, "scale_pos_weight": [1, 2, 4, 8, 14]}),
        "xgboost_smotenc": (ImbPipeline([("imp", SimpleImputer(strategy="median")),
                                         ("smote", SMOTENC(categorical_features=BINARY_IDX, sampling_strategy=0.3, k_neighbors=5, random_state=seed)),
                                         ("clf", xgb())]),
                            {**pre("clf__"), "smote__sampling_strategy": [0.15, 0.3, 0.5]}),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-iter", type=int, default=25, help="random-search iterations per candidate")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=-1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=str(ROOT / "models"))
    ap.add_argument("--target-recall", type=float, default=0.0, help="e.g. 0.70: choose the threshold reaching this recall on train CV (precision and accuracy drop); 0 = max-F1")
    ap.add_argument("--max-train-rows", type=int, default=0, help="debug only: subsample the training set")
    a = ap.parse_args()

    dirs = sorted((ROOT / "data" / "processed").glob("gmsc-v1-*-split8020"))
    if not dirs:
        sys.exit("No 80/20 split found. Put cs-training.csv in data/raw/ and run: python3 -I scripts/run_phase1.py")
    ddir = dirs[-1]
    manifest = json.loads((ddir / "manifest.json").read_text())
    Xtr, ytr = load_split(ddir, "train")
    Xte, yte = load_split(ddir, "test")
    if a.max_train_rows:
        idx = Xtr.sample(a.max_train_rows, random_state=a.seed).index
        Xtr, ytr = Xtr.loc[idx], ytr.loc[idx]
    Xtr, ytr = Xtr.reset_index(drop=True), ytr.reset_index(drop=True)
    print(f"train {len(Xtr):,} ({ytr.mean():.2%} defaults) | test {len(Xte):,} | xgboost {xgboost.__version__}", flush=True)

    oof_cv = StratifiedKFold(a.folds, shuffle=True, random_state=a.seed)
    search_cv = StratifiedKFold(3, shuffle=True, random_state=a.seed)
    best, oof, summary, search_info = {}, {}, {}, {}
    for name, (est, space) in build_candidates(a.seed, a.jobs).items():
        t0 = time.time()
        rs = RandomizedSearchCV(est, space, n_iter=a.n_iter, scoring="average_precision", cv=search_cv, n_jobs=1, refit=False,
                                random_state=a.seed, error_score="raise").fit(Xtr, ytr)
        best[name] = clone(est).set_params(**rs.best_params_)
        oof[name] = cross_val_predict(best[name], Xtr, ytr, cv=oof_cv, method="predict_proba", n_jobs=1)[:, 1]   # SMOTENC only inside each fold's fit
        summary[name] = {"oof_roc_auc": float(roc_auc_score(ytr, oof[name])), "oof_pr_auc": float(average_precision_score(ytr, oof[name]))}
        search_info[name] = {"best_params": rs.best_params_, "search_pr_auc_3fold": float(rs.best_score_)}
        print(f"[{name}] OOF ROC-AUC {summary[name]['oof_roc_auc']:.4f}  PR-AUC {summary[name]['oof_pr_auc']:.4f}  ({time.time() - t0:.0f}s)", flush=True)

    chosen = max(summary, key=lambda k: summary[k]["oof_pr_auc"])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[chosen], ytr)
    oof_cal = iso.predict(oof[chosen])
    thr = threshold_for_recall(ytr, oof_cal, a.target_recall) if a.target_recall else best_f1_threshold(ytr, oof_cal)
    rule = f"recall >= {a.target_recall} on calibrated out-of-fold train predictions" if a.target_recall else "maximise F1 on calibrated out-of-fold train predictions"
    final = IsotonicCalibrated(best[chosen].fit(Xtr, ytr), iso)          # refit on the full 80% train set
    p_test, p_train = final.predict_proba(Xte)[:, 1], final.predict_proba(Xtr)[:, 1]   # test scored once, here

    dfp = pd.DataFrame({"p": p_test, "y": yte.to_numpy()})
    dfp["bin"] = pd.qcut(dfp.p, 10, duplicates="drop")
    reliability = [{"mean_predicted": float(g.p.mean()), "observed_rate": float(g.y.mean()), "n": int(len(g))} for _, g in dfp.groupby("bin", observed=True)]
    rng = np.random.default_rng(a.seed)
    background = Xtr.iloc[rng.choice(len(Xtr), min(25, len(Xtr)), replace=False)].reset_index(drop=True)
    sample = Xtr.iloc[rng.choice(len(Xtr), min(120, len(Xtr)), replace=False)].reset_index(drop=True)
    importance = global_importance(lambda df: final.predict_proba(df)[:, 1], sample, background)

    version = f"model-{ddir.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bands = {"low_max": LOW_BAND_MAX, "high_min": round(thr, 4)}
    joblib.dump({"model": final, "features": MODEL_FEATURES, "threshold": thr, "bands": bands, "background": background, "version": version}, out / f"{version}.joblib")
    res = {"selected_model": chosen, "cv_5fold_train_oof": summary, "cv_oof_calibrated_at_threshold": metrics(ytr, oof_cal, thr),
           "train_in_sample": metrics(ytr, p_train, thr), "test": metrics(yte, p_test, thr), "gb_best_params": search_info[chosen]["best_params"],
           "candidate_search": search_info, "reliability_test_deciles": reliability, "global_importance": importance, "base_rate_train": float(ytr.mean()),
           "decision_threshold_rule": rule, "risk_bands": bands}
    meta = {"model_version": version, "dataset_version": manifest["dataset_version"], "trained_utc": datetime.now(timezone.utc).isoformat(), "random_seed": a.seed,
            "split_policy": manifest["split_policy"], "xgboost_smote_status": "xgboost trained" + (" with SMOTENC (inside CV folds)" if "smote" in chosen else ""),
            "library_versions": {"xgboost": xgboost.__version__, "scikit_learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__},
            "features": MODEL_FEATURES, "algorithm": chosen,
            "resampling": "SMOTENC inside CV folds (imblearn Pipeline)" if "smote" in chosen else ("scale_pos_weight" if "weight" in chosen else "none"), **res}
    (out / f"{version}.json").write_text(json.dumps(meta, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))

    print("\n=== RESULTS (selected: %s) ===" % chosen)
    print(f"{'split':34s} {'ROC-AUC':>8s} {'PR-AUC':>7s} {'Prec':>6s} {'Recall':>6s} {'F1':>6s} {'Acc':>6s} {'Spec':>6s} {'Brier':>7s}")
    for lab, k in [("5-fold CV (OOF, calibrated)", "cv_oof_calibrated_at_threshold"), ("train (in-sample)", "train_in_sample"), ("HELD-OUT TEST (20%)", "test")]:
        m = res[k]
        print(f"{lab:34s} {m['roc_auc']:8.4f} {m['pr_auc']:7.4f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} {m['accuracy']:6.3f} {m['specificity']:6.3f} {m['brier']:7.4f}")
    print("test confusion matrix:", res["test"]["confusion_matrix"], "| threshold", round(thr, 4))
    print("candidates (OOF PR-AUC):", {k: round(v["oof_pr_auc"], 4) for k, v in summary.items()})
    print(f"\nSaved: {out / (version + '.joblib')}\nRestart the app (python3 scripts/serve.py) to serve this model.")


if __name__ == "__main__":
    main()
