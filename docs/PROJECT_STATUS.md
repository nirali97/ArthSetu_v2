# ArthSetu V2 — Project status (2026-11-06)

## Done and verified (by running)
- Phase 0 audit; Phase 1 data pipeline (80/20 stratified split, reproducible version `gmsc-v1-d816fcae-split8020`).
- Phase 2: baseline LR, HistGradientBoosting (tuned), own SMOTE inside CV folds, isotonic calibration, threshold, single test evaluation, Shapley explainer.
- Phase 3: backend (auth, sessions, RBAC, assessments, history/export, explanations, chat + Groq proxy with KB fallback, admin, audit, rate limits, CSRF).
- Phase 4–5: SPA (landing, auth, dashboard, assessment form, result + explanation, history, model page, settings, admin console, chat widget), EN/HI, dark/light.
- Phase 6: integration workflow test; browser E2E.

## Tests actually run
`pytest`: **43 passed** (19 data/ML, 24 API incl. full register→login→assess→explain→chat→logout→admin-verify workflow). `run_e2e.py`: **32/32 passed** (Chromium).

## Not implemented / not verified
- XGBoost training, imblearn SMOTE, `shap` library — packages unavailable (optional code path exists, untested).
- FastAPI/SQLAlchemy/Alembic/PostgreSQL/Argon2id/React/TS/Tailwind/shadcn/Recharts — replaced as documented in ARCHITECTURE_API.md.
- Live Groq call, PostgreSQL run, load testing, native-speaker Hindi review, frontend unit tests, HTTPS cookie behaviour (Secure flag untested over TLS).
- Dataset is US consumer credit, not Indian MSME.

## Next
`pip install xgboost imbalanced-learn`, rerun train.py (auto-adds xgboost_smote), verify; set Groq key and test live; move to PostgreSQL if multi-instance.
