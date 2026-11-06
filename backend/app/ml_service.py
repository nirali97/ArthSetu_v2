"""Loads the trained artifact once and serves predictions + Shapley explanations with the SAME feature code as training."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ml.explain import shapley  # noqa: E402
from ml.features.engineering import MODEL_FEATURES, engineer_features  # noqa: E402

INPUT_MAP = {
    "revolving_utilization": "RevolvingUtilizationOfUnsecuredLines", "age": "age",
    "past_due_30_59": "NumberOfTime30-59DaysPastDueNotWorse", "debt_ratio": "DebtRatio", "monthly_income": "MonthlyIncome",
    "open_credit_lines": "NumberOfOpenCreditLinesAndLoans", "past_due_90_plus": "NumberOfTimes90DaysLate",
    "real_estate_loans": "NumberRealEstateLoansOrLines", "past_due_60_89": "NumberOfTime60-89DaysPastDueNotWorse",
    "dependents": "NumberOfDependents",
}


class ModelService:
    def __init__(self, models_dir: str):
        files = sorted(Path(models_dir).glob("model-*.joblib"))
        self.loaded = bool(files)
        self.art = self.meta = None
        if files:
            self.art = joblib.load(files[-1])
            self.meta = json.loads(files[-1].with_suffix(".json").read_text())
            assert self.art["features"] == MODEL_FEATURES, "artifact/feature schema mismatch"

    @property
    def version(self) -> str:
        return self.art["version"]

    def band(self, p: float) -> str:
        b = self.art["bands"]
        return "LOW" if p < b["low_max"] else "HIGH" if p >= b["high_min"] else "MODERATE"

    def predict(self, inputs: dict, n_perm: int = 60) -> dict:
        if not self.loaded:
            raise RuntimeError("model not loaded")
        raw = pd.DataFrame([{INPUT_MAP[k]: (np.nan if v is None else float(v)) for k, v in inputs.items() if k in INPUT_MAP}])
        X = engineer_features(raw)
        f = lambda df: self.art["model"].predict_proba(df)[:, 1]  # noqa: E731
        sh = shapley(f, X, self.art["background"], n_perm=n_perm, seed=7)  # fixed seed -> reproducible explanation
        p = float(sh["prediction"])
        contribs = sorted(({"feature": c, "value": None if np.isnan(X.iloc[0][c]) else float(X.iloc[0][c]),
                            "contribution": sh["contributions"][c], "std_error": sh["std_error"][c]} for c in MODEL_FEATURES),
                          key=lambda r: -abs(r["contribution"]))
        return {"probability": p, "risk_band": self.band(p), "threshold": float(self.art["threshold"]), "model_version": self.version,
                "explanation": {"method": "shapley_permutation_sampling", "unit": "probability_points", "base_value": sh["base_value"],
                                "prediction": p, "contributions": contribs}}
