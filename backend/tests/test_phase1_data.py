import numpy as np
import pandas as pd
import pytest

from ml.data.clean import clean_training_data
from ml.data.schema import RAW_COLUMNS, RAW_FEATURES, TARGET, SchemaError, validate_raw
from ml.data.split import stratified_split
from ml.features.engineering import FEATURE_SPECS, MODEL_FEATURES, engineer_features


def make_df(n=400, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        TARGET: (rng.random(n) < 0.1).astype(int),
        "RevolvingUtilizationOfUnsecuredLines": rng.random(n) * 1.5,
        "age": rng.integers(21, 80, n),
        "NumberOfTime30-59DaysPastDueNotWorse": rng.integers(0, 3, n),
        "DebtRatio": rng.random(n),
        "MonthlyIncome": rng.integers(1000, 9000, n).astype(float),
        "NumberOfOpenCreditLinesAndLoans": rng.integers(0, 15, n),
        "NumberOfTimes90DaysLate": rng.integers(0, 2, n),
        "NumberRealEstateLoansOrLines": rng.integers(0, 3, n),
        "NumberOfTime60-89DaysPastDueNotWorse": rng.integers(0, 2, n),
        "NumberOfDependents": rng.integers(0, 4, n).astype(float),
    })
    return df[RAW_COLUMNS]


def test_validate_ok():
    validate_raw(make_df())


def test_validate_missing_column():
    with pytest.raises(SchemaError):
        validate_raw(make_df().drop(columns=["age"]))


def test_validate_bad_target_and_negative():
    df = make_df()
    df.loc[0, TARGET] = 2
    with pytest.raises(SchemaError):
        validate_raw(df)
    df = make_df()
    df.loc[0, "age"] = -1
    with pytest.raises(SchemaError):
        validate_raw(df)


def test_clean_rules():
    df = make_df(50)
    df.loc[0, "age"] = 0
    df.loc[1, "NumberOfTimes90DaysLate"] = 98
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)  # exact duplicate
    out, log = clean_training_data(df)
    assert log["rows_dropped_age_lt_18"] == 1
    assert log["duplicate_rows_dropped"] == 1
    assert log["sentinel_cells_set_to_nan"] == 1
    assert out["NumberOfTimes90DaysLate"].isna().sum() == 1
    assert len(out) == 49 - 0  # 51 in - 1 age - 1 duplicate


def test_feature_columns_and_order():
    f = engineer_features(make_df())
    assert list(f.columns) == MODEL_FEATURES
    assert [s.name for s in FEATURE_SPECS] == MODEL_FEATURES


def test_zero_and_missing_income_handled():
    df = make_df(10)
    df.loc[0, "MonthlyIncome"] = 0
    df.loc[1, "MonthlyIncome"] = np.nan
    f = engineer_features(df)
    for i in (0, 1):
        assert f.loc[i, "income_reported"] == 0
        assert np.isnan(f.loc[i, "debt_ratio_valid"])
        assert np.isnan(f.loc[i, "income_per_household_member"])
    assert not np.isinf(f.to_numpy()).any()


def test_derived_formulas():
    df = make_df(5)
    df.loc[2, ["MonthlyIncome", "DebtRatio", "NumberOfDependents"]] = [4000.0, 0.5, 3.0]
    f = engineer_features(df)
    assert f.loc[2, "est_monthly_obligations"] == pytest.approx(2000.0)
    assert f.loc[2, "income_per_household_member"] == pytest.approx(1000.0)


def test_sentinel_nan_propagates():
    df = make_df(5)
    df.loc[0, "NumberOfTimes90DaysLate"] = np.nan
    f = engineer_features(df)
    assert np.isnan(f.loc[0, "total_past_due_events"])
    assert np.isnan(f.loc[0, "has_90plus_delinquency"])


def test_inference_single_row_matches_batch():
    df = make_df(20)
    batch = engineer_features(df.drop(columns=[TARGET]))
    one = engineer_features(df.drop(columns=[TARGET]).iloc[[7]])
    pd.testing.assert_series_equal(batch.iloc[7], one.iloc[0], check_names=False)


def test_missing_raw_feature_rejected():
    with pytest.raises(ValueError):
        engineer_features(make_df().drop(columns=["DebtRatio"]))


def test_split_stratified_disjoint_deterministic():
    df = make_df(2000)
    s1 = stratified_split(df, TARGET, seed=1)
    s2 = stratified_split(df, TARGET, seed=1)
    assert sum(len(v) for v in s1.values()) == len(df)
    idx = [set(v.index) for v in s1.values()]
    assert not (idx[0] & idx[1]) and not (idx[0] & idx[2]) and not (idx[1] & idx[2])
    for k in s1:
        pd.testing.assert_frame_equal(s1[k], s2[k])
        assert abs(s1[k][TARGET].mean() - df[TARGET].mean()) < 0.01
    assert len(s1["val"]) == pytest.approx(300, abs=2) and len(s1["test"]) == pytest.approx(300, abs=2)
    s3 = stratified_split(df, TARGET, seed=1, val_size=0.0, test_size=0.2)
    assert set(s3) == {"train", "test"} and len(s3["test"]) == pytest.approx(0.2 * len(df), abs=2)
    assert abs(s3["train"][TARGET].mean() - s3["test"][TARGET].mean()) < 0.01
