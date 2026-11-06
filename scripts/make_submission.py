"""Score Kaggle's cs-test.csv with the newest model in models/ and write a Kaggle-format submission (Id,Probability).

    python3 -I scripts/make_submission.py

cs-test.csv has NO labels, so it cannot be scored locally. Upload the generated CSV to Kaggle
(Give Me Some Credit -> "Late Submission") and Kaggle reports the ROC-AUC, which is the competition's metric.
Every one of the 101,503 Ids must be present, so no rows are dropped: invalid ages become missing, sentinel codes
(96/98) become missing, and the model handles missing values natively.
"""
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from ml.data.ingest import load_raw  # noqa: E402
from ml.data.schema import PAST_DUE_COLS, SENTINEL_CODES  # noqa: E402
from ml.features.engineering import MODEL_FEATURES, engineer_features  # noqa: E402

files = sorted((ROOT / "models").glob("model-*.joblib"))
if not files:
    sys.exit("No model in models/. Train one first.")
art = joblib.load(files[-1])
assert art["features"] == MODEL_FEATURES, "model/feature schema mismatch"

test = load_raw(ROOT / "data" / "raw" / "cs-test.csv", require_target=False)
test = test.copy()
test[PAST_DUE_COLS] = test[PAST_DUE_COLS].mask(test[PAST_DUE_COLS].isin(SENTINEL_CODES))
test.loc[test["age"] < 18, "age"] = np.nan                      # keep the row; the model handles missing
proba = art["model"].predict_proba(engineer_features(test)[MODEL_FEATURES])[:, 1]

sample = pd.read_csv(ROOT / "data" / "raw" / "sampleEntry.csv")
sub = pd.DataFrame({"Id": test.index.to_numpy(), "Probability": proba})
assert len(sub) == len(sample) and set(sub["Id"]) == set(sample["Id"]), "Ids do not match sampleEntry.csv"
assert sub["Probability"].between(0, 1).all() and sub["Probability"].notna().all()
out = ROOT / "submissions"
out.mkdir(exist_ok=True)
path = out / f"submission_{art['version']}.csv"
sub.sort_values("Id").to_csv(path, index=False)
print(f"model {art['version']}\nrows {len(sub):,} | mean probability {proba.mean():.4f} (training default rate ~0.067)\nsaved {path}")
