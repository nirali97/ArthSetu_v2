"""Data-quality assessment of the raw training data (read-only; changes nothing)."""
from __future__ import annotations

import pandas as pd

from ml.data.schema import PAST_DUE_COLS, RAW_FEATURES, SENTINEL_CODES, TARGET


def quality_report(df: pd.DataFrame) -> dict:
    n = len(df)
    r: dict = {"n_rows": int(n), "n_cols": int(df.shape[1])}

    y = df[TARGET]
    r["target_counts"] = {int(k): int(v) for k, v in y.value_counts().sort_index().items()}
    r["positive_rate"] = float(y.mean())

    r["missing"] = {
        c: {"count": int(k), "pct": round(100 * k / n, 2)} for c, k in df.isna().sum().items() if k > 0
    }
    r["exact_duplicate_rows"] = int(df.duplicated().sum())

    r["sentinel_counts"] = {
        c: {int(code): int((df[c] == code).sum()) for code in SENTINEL_CODES} for c in PAST_DUE_COLS
    }
    r["rows_with_sentinel_in_all_three"] = int(df[PAST_DUE_COLS].isin(SENTINEL_CODES).all(axis=1).sum())

    r["age_lt_18"] = int((df["age"] < 18).sum())
    r["age_gt_100"] = int((df["age"] > 100).sum())
    util = df["RevolvingUtilizationOfUnsecuredLines"]
    r["utilization_gt_1"] = int((util > 1).sum())
    r["utilization_gt_10"] = int((util > 10).sum())
    r["debt_ratio_gt_1"] = int((df["DebtRatio"] > 1).sum())
    r["income_zero"] = int((df["MonthlyIncome"] == 0).sum())

    no_income = df["MonthlyIncome"].isna()
    r["income_missing_vs_present"] = {
        "debt_ratio_median_when_income_missing": float(df.loc[no_income, "DebtRatio"].median()),
        "debt_ratio_median_when_income_present": float(df.loc[~no_income, "DebtRatio"].median()),
        "default_rate_when_income_missing": float(y[no_income].mean()),
        "default_rate_when_income_present": float(y[~no_income].mean()),
    }

    outliers = {}
    for c in RAW_FEATURES:
        s = df[c].dropna()
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        outliers[c] = {
            "p01": float(s.quantile(0.01)),
            "p99": float(s.quantile(0.99)),
            "max": float(s.max()),
            "n_beyond_3xIQR_fence": int(((s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)).sum()),
        }
    r["outliers"] = outliers
    return r


def render_quality_markdown(report: dict, cleaning_log: dict, source_info: dict) -> str:
    L: list[str] = ["# Data quality report — GMSC `cs-training.csv`", ""]
    L += [
        f"Source file sha256: `{source_info['sha256']}`",
        f"Rows: {report['n_rows']:,}  |  Columns: {report['n_cols']}",
        "",
        "## Target (`SeriousDlqin2yrs`)",
        f"Counts: {report['target_counts']}  |  default rate: {report['positive_rate']:.4%}",
        "",
        "## Missing values",
        "| Column | Missing | % |",
        "|---|---|---|",
    ]
    for c, v in report["missing"].items():
        L.append(f"| {c} | {v['count']:,} | {v['pct']}% |")
    m = report["income_missing_vs_present"]
    L += [
        "",
        "Missing `MonthlyIncome` is not harmless: where it is missing, `DebtRatio` has a median of "
        f"{m['debt_ratio_median_when_income_missing']:.1f} versus {m['debt_ratio_median_when_income_present']:.3f} "
        "where income is present, i.e. it behaves like an absolute amount rather than a ratio. "
        f"Default rate is {m['default_rate_when_income_missing']:.2%} (income missing) vs "
        f"{m['default_rate_when_income_present']:.2%} (income present).",
        "",
        "## Invalid / suspicious values",
        f"- Exact duplicate rows: {report['exact_duplicate_rows']:,}",
        f"- Sentinel codes 96/98 in past-due columns: {report['sentinel_counts']} "
        f"(rows where all three columns carry a sentinel: {report['rows_with_sentinel_in_all_three']})",
        f"- age < 18: {report['age_lt_18']}  |  age > 100: {report['age_gt_100']}",
        f"- Utilization > 1: {report['utilization_gt_1']:,}  |  > 10: {report['utilization_gt_10']:,}",
        f"- DebtRatio > 1: {report['debt_ratio_gt_1']:,}  |  MonthlyIncome == 0: {report['income_zero']:,}",
        "",
        "## Outliers (no clipping applied at this stage)",
        "| Column | p1 | p99 | max | beyond 3×IQR |",
        "|---|---|---|---|---|",
    ]
    for c, o in report["outliers"].items():
        L.append(f"| {c} | {o['p01']:.4g} | {o['p99']:.4g} | {o['max']:.4g} | {o['n_beyond_3xIQR_fence']:,} |")
    L += [
        "",
        "## Cleaning applied (deterministic, learns nothing from data)",
        *[f"- {k}: {v:,}" for k, v in cleaning_log.items()],
        "",
        "## Dataset representativeness and leakage notes",
        "- US consumer credit data (2011). Not Indian, not MSME. Results say nothing about Indian borrowers.",
        "- `cs-test.csv` has no labels (target column empty), so it cannot be used for evaluation; "
        "a labelled validation and test set are carved out of `cs-training.csv`.",
        "- No timestamps or applicant ids: temporal splitting is impossible, and exact-duplicate removal cannot "
        "distinguish a true duplicate from two similar applicants.",
        "- The past-due count columns carry no observation-window definition for the 90-day count in the data "
        "dictionary; any overlap with the 2-year target window cannot be checked from this data. Treat their "
        "predictive strength with caution.",
        "- Outlier clipping, imputation and scaling are fit on the training split only (Phase 2 pipeline).",
    ]
    return "\n".join(L) + "\n"
