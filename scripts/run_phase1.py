"""Phase 1 pipeline: ingest -> validate -> quality report -> clean -> features -> split -> versioned outputs.

Usage: python3 -I scripts/run_phase1.py [--raw-dir data/raw] [--out-dir data/processed] [--seed 42]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402
import sklearn  # noqa: E402

from ml.data.clean import clean_training_data  # noqa: E402
from ml.data.ingest import load_raw, sha256_file  # noqa: E402
from ml.data.quality import quality_report, render_quality_markdown  # noqa: E402
from ml.data.schema import TARGET  # noqa: E402
from ml.data.split import stratified_split  # noqa: E402
from ml.features.engineering import MODEL_FEATURES, engineer_features, render_feature_dictionary  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-size", type=float, default=0.20, help="test fraction; no separate validation split (CV inside train)")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    train_path, test_path = raw_dir / "cs-training.csv", raw_dir / "cs-test.csv"

    raw = load_raw(train_path, require_target=True)
    report = quality_report(raw)
    cleaned, log = clean_training_data(raw)

    feats = engineer_features(cleaned)
    data = feats.copy()
    data[TARGET] = cleaned[TARGET].astype(int)

    digest = hashlib.sha256(data.to_csv().encode()).hexdigest()
    version = f"gmsc-v1-{digest[:8]}-split{round((1-args.test_size)*100)}{round(args.test_size*100)}"
    splits = stratified_split(data, TARGET, seed=args.seed, val_size=0.0, test_size=args.test_size)

    out = Path(args.out_dir) / version
    out.mkdir(parents=True, exist_ok=True)
    for name, part in splits.items():
        part.to_csv(out / f"{name}.csv")

    # The unlabelled competition test file is only used to prove the inference schema works on it.
    unl = load_raw(test_path, require_target=False)
    unl_feats = engineer_features(unl)

    manifest = {
        "dataset_version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": args.seed,
        "source_files": {"cs-training.csv": sha256_file(train_path), "cs-test.csv": sha256_file(test_path)},
        "cleaning_log": log,
        "model_features": MODEL_FEATURES,
        "target": TARGET,
        "split": {
            k: {"rows": int(len(v)), "positive_rate": round(float(v[TARGET].mean()), 6)} for k, v in splits.items()
        },
        "unlabelled_test_file": {"rows": int(len(unl)), "feature_frame_shape": list(unl_feats.shape),
                                 "note": "no labels; not used for training or evaluation"},
        "library_versions": {"pandas": pd.__version__, "scikit_learn": sklearn.__version__},
        "split_policy": f"stratified {round((1-args.test_size)*100)}/{round(args.test_size*100)} train/test on cleaned+deduplicated cs-training.csv; validation = 5-fold CV inside train; test untouched until final evaluation",
        "preprocessing_deferred_to_training_pipeline": ["imputation (median)", "winsorizing", "scaling for linear baseline", "SMOTE (train folds only)"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "data_quality_report.md").write_text(
        render_quality_markdown(report, log, {"sha256": sha256_file(train_path)})
    )
    (docs / "feature_dictionary.md").write_text(render_feature_dictionary())

    print(json.dumps({"version": version, "cleaning": log, "split": manifest["split"],
                      "unlabelled_feature_shape": manifest["unlabelled_test_file"]["feature_frame_shape"]}, indent=2))


if __name__ == "__main__":
    main()
