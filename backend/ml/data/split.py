"""Stratified train / (optional validation) / test split."""
from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split


def stratified_split(
    df: pd.DataFrame, target: str, seed: int = 42, val_size: float = 0.15, test_size: float = 0.15
) -> dict[str, pd.DataFrame]:
    """Split with identical class ratios. val_size=0 gives a plain train/test split (e.g. 80/20);
    model selection then uses cross-validation inside train. Deterministic for a given seed."""
    if val_size < 0 or test_size <= 0 or val_size + test_size >= 1:
        raise ValueError("need val_size >= 0, test_size > 0, val_size + test_size < 1")
    train_val, test = train_test_split(df, test_size=test_size, stratify=df[target], random_state=seed)
    if val_size == 0:
        return {"train": train_val, "test": test}
    train, val = train_test_split(train_val, test_size=val_size / (1 - test_size), stratify=train_val[target], random_state=seed)
    return {"train": train, "val": val, "test": test}
