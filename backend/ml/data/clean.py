"""Deterministic, row-level cleaning. No statistics are learned here (no imputation, no clipping),
so applying it before the train/validation/test split cannot leak information."""
from __future__ import annotations

import pandas as pd

from ml.data.schema import PAST_DUE_COLS, SENTINEL_CODES


def clean_training_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return (cleaned_df, log).

    Rules, in order:
      1. Drop rows with age < 18 (outside the adult-borrower scope; includes age == 0).
      2. Drop exact duplicate rows (all columns incl. target; first occurrence kept).
         The data has no applicant id, so an identical row could in principle be two people; this is
         accepted to avoid the same record landing in both train and test.
      3. Set sentinel codes (96, 98) in the past-due count columns to NaN.
         Imputation happens later, inside the training-only model pipeline.
    """
    log: dict = {"rows_in": int(len(df))}
    out = df.copy()

    bad_age = out["age"] < 18
    log["rows_dropped_age_lt_18"] = int(bad_age.sum())
    out = out.loc[~bad_age]

    n = len(out)
    out = out.drop_duplicates(keep="first")
    log["duplicate_rows_dropped"] = int(n - len(out))

    sentinel = out[PAST_DUE_COLS].isin(SENTINEL_CODES)
    log["sentinel_cells_set_to_nan"] = int(sentinel.to_numpy().sum())
    log["rows_with_sentinel"] = int(sentinel.any(axis=1).sum())
    out[PAST_DUE_COLS] = out[PAST_DUE_COLS].mask(sentinel)

    log["rows_out"] = int(len(out))
    return out, log
