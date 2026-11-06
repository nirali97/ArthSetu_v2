"""Raw-data schema for the Give Me Some Credit (GMSC) dataset and validation."""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "SeriousDlqin2yrs"

PAST_DUE_COLS = [
    "NumberOfTime30-59DaysPastDueNotWorse",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfTimes90DaysLate",
]

RAW_FEATURES = [
    "RevolvingUtilizationOfUnsecuredLines",
    "age",
    "NumberOfTime30-59DaysPastDueNotWorse",
    "DebtRatio",
    "MonthlyIncome",
    "NumberOfOpenCreditLinesAndLoans",
    "NumberOfTimes90DaysLate",
    "NumberRealEstateLoansOrLines",
    "NumberOfTime60-89DaysPastDueNotWorse",
    "NumberOfDependents",
]
RAW_COLUMNS = [TARGET] + RAW_FEATURES

# Codes 96 and 98 in the past-due count columns are placeholder values, not real counts.
SENTINEL_CODES = (96, 98)


class SchemaError(ValueError):
    """Raised when the input data violates the expected schema."""


def validate_raw(df: pd.DataFrame, require_target: bool = True) -> None:
    """Hard schema checks. Raises SchemaError on the first group of violations.

    Soft data-quality issues (missing values, sentinels, duplicates, outliers) are NOT errors here;
    they are reported by quality.py and handled by clean.py.
    """
    required = RAW_COLUMNS if require_target else RAW_FEATURES
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SchemaError(f"Missing required columns: {missing}")

    for col in required:
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise SchemaError(f"Column {col!r} is not numeric (dtype={df[col].dtype})")

    values = df[required].to_numpy(dtype=float)
    if np.isinf(values).any():
        raise SchemaError("Infinite values found")

    if require_target:
        y = df[TARGET]
        if y.isna().any():
            raise SchemaError("Target contains missing values")
        if not set(y.unique()).issubset({0, 1}):
            raise SchemaError("Target must be binary (0/1)")

    negatives = [c for c in RAW_FEATURES if (df[c] < 0).any()]
    if negatives:
        raise SchemaError(f"Negative values in non-negative columns: {negatives}")
