"""Raw data ingestion with schema validation."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ml.data.schema import RAW_FEATURES, TARGET, validate_raw


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(path: str | Path, require_target: bool = True) -> pd.DataFrame:
    """Load a GMSC csv (first column is the row id) and validate its schema.

    With require_target=False (unlabelled competition test file) the target column, if present,
    is dropped and only feature columns are validated.
    """
    df = pd.read_csv(path, index_col=0)
    df.index.name = "row_id"
    validate_raw(df, require_target=require_target)
    if not require_target and TARGET in df.columns:
        df = df.drop(columns=[TARGET])
    return df[([TARGET] if require_target else []) + RAW_FEATURES]
