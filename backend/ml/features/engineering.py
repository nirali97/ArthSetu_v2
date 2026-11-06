"""Feature engineering shared by training and inference (single source of truth for the model schema).

Every function here is deterministic and uses constants only; nothing is learned from data, so it is
safe to apply before splitting. Learned steps (imputation, winsorizing, scaling) live in the Phase 2 pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ml.data.schema import PAST_DUE_COLS, RAW_FEATURES

P30, P60, P90 = PAST_DUE_COLS[0], PAST_DUE_COLS[1], PAST_DUE_COLS[2]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str  # "numerical" (raw, passed through) or "derived"
    dtype: str  # "numeric", "count" or "binary"
    inputs: str
    formula: str
    significance: str
    edge_cases: str
    leakage: str


_NO_LEAK = "Uses only applicant attributes known at application time; not derived from the target."

FEATURE_SPECS: list[FeatureSpec] = [
    FeatureSpec("RevolvingUtilizationOfUnsecuredLines", "numerical", "numeric", "raw column",
                "balance on revolving unsecured credit / total credit limits",
                "How much of available revolving credit is used; high use signals financial stress.",
                "Raw values reach 50,708; clipped in the training-only pipeline.", _NO_LEAK),
    FeatureSpec("age", "numerical", "count", "raw column", "age in years",
                "Life-stage proxy for stability and earnings.", "Rows with age < 18 removed.",
                _NO_LEAK + " Age-based models raise fairness concerns; see docs."),
    FeatureSpec("MonthlyIncome", "numerical", "numeric", "raw column", "monthly gross income",
                "Repayment capacity.", "~19.8% missing (imputed in-pipeline, with `income_reported` flag); 0 treated as unreported in derived features.",
                _NO_LEAK),
    FeatureSpec("NumberOfOpenCreditLinesAndLoans", "numerical", "count", "raw column",
                "count of open loans and credit lines", "Breadth of existing credit relationships.", "None.", _NO_LEAK),
    FeatureSpec("NumberRealEstateLoansOrLines", "numerical", "count", "raw column",
                "count of mortgage / real-estate loans and HELOCs", "Secured-debt exposure.", "None.", _NO_LEAK),
    FeatureSpec("NumberOfDependents", "numerical", "count", "raw column", "dependents excluding the borrower",
                "Household obligations.", "~2.6% missing (imputed in-pipeline).", _NO_LEAK),
    FeatureSpec(P30, "numerical", "count", "raw column", "times 30–59 days past due in last 2 years",
                "Early-stage repayment problems.", "Sentinel 96/98 set to NaN.",
                "Observation window overlaps the period before the target window; exact overlap unverifiable."),
    FeatureSpec(P60, "numerical", "count", "raw column", "times 60–89 days past due in last 2 years",
                "Moderate repayment problems.", "Sentinel 96/98 set to NaN.",
                "Same window caveat as the 30–59 column."),
    FeatureSpec(P90, "numerical", "count", "raw column", "times 90+ days past due",
                "Serious repayment problems; the target itself is 90+ days past due.", "Sentinel 96/98 set to NaN.",
                "HIGH-RISK for leakage: the dictionary gives no time window for this count and it is conceptually "
                "close to the target. Cannot be verified without timestamps; documented as a limitation."),
    FeatureSpec("income_reported", "derived", "binary", "MonthlyIncome",
                "1 if MonthlyIncome is present and > 0, else 0",
                "Missing income correlates with how DebtRatio behaves and with default rate; the model should know it.",
                "NaN or 0 income -> 0.", _NO_LEAK),
    FeatureSpec("debt_ratio_valid", "derived", "numeric", "DebtRatio, MonthlyIncome",
                "DebtRatio if income_reported == 1 else NaN",
                "Debt-to-income burden (monthly obligations / monthly income) restricted to rows where it is a real ratio.",
                "When income is unreported, DebtRatio is NaN (it behaves like an absolute amount there). "
                "Information loss from this choice should be checked by ablation in Phase 2.", _NO_LEAK),
    FeatureSpec("est_monthly_obligations", "derived", "numeric", "DebtRatio, MonthlyIncome",
                "DebtRatio * MonthlyIncome if income_reported == 1 else NaN",
                "Approximate absolute monthly debt/living obligations (per dictionary definition of DebtRatio).",
                "NaN when income unreported. Currency not stated in the source.", _NO_LEAK),
    FeatureSpec("income_per_household_member", "derived", "numeric", "MonthlyIncome, NumberOfDependents",
                "MonthlyIncome / (NumberOfDependents + 1) if income_reported == 1 else NaN",
                "Income available per person supported (borrower + dependents).",
                "Denominator >= 1, never zero. NaN if income unreported or dependents missing.", _NO_LEAK),
    FeatureSpec("total_past_due_events", "derived", "count", "three past-due count columns",
                "30–59 + 60–89 + 90+ counts",
                "Overall delinquency history.", "NaN if any component is NaN (sentinel rows).",
                "Inherits the 90+ column's window caveat."),
    FeatureSpec("has_90plus_delinquency", "derived", "binary", P90, "1 if 90+ count > 0 else 0",
                "Any serious delinquency on record.", "NaN where the count is NaN.",
                "Inherits the 90+ column's window caveat."),
    FeatureSpec("utilization_over_limit", "derived", "binary", "RevolvingUtilizationOfUnsecuredLines",
                "1 if utilization > 1 else 0", "Balance above credit limit.", "None.", _NO_LEAK),
]

MODEL_FEATURES: list[str] = [s.name for s in FEATURE_SPECS]


def engineer_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Build the model feature frame (columns in MODEL_FEATURES order) from cleaned raw features.

    Works identically for training rows and single-applicant inference input.
    """
    missing = [c for c in RAW_FEATURES if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing raw feature columns: {missing}")

    income = raw["MonthlyIncome"]
    reported = income.notna() & (income > 0)
    out = pd.DataFrame(index=raw.index)

    for name in [
        "RevolvingUtilizationOfUnsecuredLines", "age", "MonthlyIncome", "NumberOfOpenCreditLinesAndLoans",
        "NumberRealEstateLoansOrLines", "NumberOfDependents", P30, P60, P90,
    ]:
        out[name] = raw[name].astype(float)

    out["income_reported"] = reported.astype(float)
    out["debt_ratio_valid"] = raw["DebtRatio"].astype(float).where(reported)
    out["est_monthly_obligations"] = (raw["DebtRatio"] * income).where(reported)
    out["income_per_household_member"] = (income / (raw["NumberOfDependents"] + 1)).where(reported)
    out["total_past_due_events"] = raw[PAST_DUE_COLS].sum(axis=1, skipna=False)
    out["has_90plus_delinquency"] = (raw[P90] > 0).astype(float).where(raw[P90].notna())
    out["utilization_over_limit"] = (raw["RevolvingUtilizationOfUnsecuredLines"] > 1).astype(float)
    return out[MODEL_FEATURES]


def render_feature_dictionary() -> str:
    L = [
        "# Feature dictionary", "",
        "Source: GMSC `cs-training.csv` (US consumer credit, 2011). Only features the data supports are built; "
        "revenue growth, cash-flow stability, transaction regularity, savings behaviour, business history and "
        "working-capital indicators are NOT available in this dataset and are therefore NOT implemented.", "",
        "| Feature | Group | Type | Inputs | Formula | Financial significance | Edge cases | Leakage check |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in FEATURE_SPECS:
        L.append(f"| `{s.name}` | {s.group} | {s.dtype} | {s.inputs} | {s.formula} | {s.significance} | "
                 f"{s.edge_cases} | {s.leakage} |")
    L += ["", "Raw `DebtRatio` is not passed to the model directly; it enters as `debt_ratio_valid` "
          "(see edge cases). There are no true categorical variables in this dataset; binary flags are derived."]
    return "\n".join(L) + "\n"
