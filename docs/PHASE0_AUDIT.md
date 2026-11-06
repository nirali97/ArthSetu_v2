# Phase 0 — Audit of the original ArthSetu repo

Source: https://github.com/ASH-2012/Arthsetu (1 commit, `b6c117c`). Audited 2026-11-05 from a shallow clone.
I read: README, backend/main.py, schemas.py, utils/shap_explainer.py, both notebooks, docker-compose.yml, requirements.in, and the first 40 lines of CreditForm.js (778 lines; the rest was not reviewed).

## What the repo actually contains
- FastAPI app with one endpoint `POST /api/v1/evaluate`, 5 input features, SHAP explanations, no auth, no database.
- Two notebooks (01 EDA/cleaning, 03 XGBoost+SHAP). There is no notebook 02.
- CRA (JavaScript) React frontend; a single large `CreditForm.js`.
- `backend/models/train.py` is an empty file (0 bytes). No dataset and no model artifact (`.pkl`) is committed.

## Findings

### Critical
1. **Backend cannot start from the repo.** `main.py` raises on startup if `models/arthsetu_xgb.pkl` is missing, and that file is not in the repo.
2. **Fabricated features.** The notebook builds the model's inputs from Give Me Some Credit columns by relabelling:
   - `Savings_Balance = MonthlyIncome * 1.5` (invented; a deterministic function of income)
   - `Credit_History_Length_Months = age*12 - 216` (this is age, not credit history)
   - `Utility_Bill_Late_Count` = sum of credit-delinquency counts (not utility bills)
   - `Income_Annual` is labelled INR but the source income is US-dollar consumer data
3. **Fake SHAP fallback.** On any SHAP error, `main.py` returns hard-coded factors ("Income_Annual 0.12", "Utility_Bill_Late_Count 0.22") as if real. This breaks the "no fabricated explanations" rule.
4. **Train-set leakage.** Median imputation and 99th-percentile clipping are fit on the full dataset before the train/test split.
5. **Arbitrary lending decisions.** `max_approval_limit` is hard-coded (300000 / 100000 / 0) from probability bands; this is not decision-support.

### High
6. SMOTE is applied correctly after the split but outside an imblearn `Pipeline`, with no cross-validation. Probabilities from a SMOTE-trained model are not calibrated, yet the 0.3/0.7 risk bands and the score formula treat them as real default probabilities.
7. No metrics are recorded anywhere (no evaluation, no threshold choice, no calibration, no model/dataset versioning).
8. The credit-score formula is discontinuous (e.g. p=0.30 gives 810 in the Low band, 640 in the Medium band).
9. SHAP messages say a feature "impacted the score by X%"; SHAP values are in log-odds, not percent. `impact` uses abs(), which discards direction apart from the list it lands in.
10. CORS is `allow_origins=["*"]`; no auth, rate limiting, or audit trail; 500 errors return `str(e)` to the client.
11. README says Random Forest; code uses XGBoost.
12. `CreditForm.js` contains a hard-coded mock response (I did not verify whether it is used at runtime).

### Medium / Low
13. SHAP `TreeExplainer` is rebuilt on every request. Frontend is JavaScript, not TypeScript. `boto3` is listed but unused in the files I read.

## Reusable vs rebuild
- **Keep as concepts:** fail-fast model load at startup, Pydantic request/response schemas, splitting SHAP output into risk-raising / risk-lowering factors, Docker Compose skeleton.
- **Rebuild:** everything else (data pipeline, features, training, evaluation, calibration, explainability layer, API, auth, DB, frontend).

## Dataset suitability
The only dataset referenced is Kaggle "Give Me Some Credit" (GMSC): US consumer credit data, 2011, ~150k rows, 11 columns (data dictionary attached by the user). It is **not** Indian and **not** MSME data. It has no revenue, cash-flow, transaction, savings or business-history fields, so those features cannot be engineered from it and will not be invented. The README's "Indian alternative credit" framing has to be presented as a limitation: this is a prototype on US consumer data.
Known GMSC properties to **verify once the data is available** (from its public description, not yet checked by me): ~6.7% positive class, ~20% missing `MonthlyIncome`, missing `NumberOfDependents`, `age`=0 rows, sentinel values 96/98 in the past-due count columns, extreme `DebtRatio` where income is missing.

## Environment audit (this workspace)
- Installed: pandas, numpy, scikit-learn, pydantic, uvicorn, pytest, joblib, openpyxl; Node 22 / npm; PostgreSQL 16 client.
- Missing: xgboost, imbalanced-learn, shap, fastapi, sqlalchemy, alembic, argon2-cffi, groq, psycopg2, xlrd. Package installs are blocked for this account.
- No dataset present; Kaggle is unreachable from the workspace.
