# ArthSetu V2 — credit-risk decision support (prototype)

Explainable default-probability estimates with real signup/login, per-user history, per-applicant explanations, an AI assistant,
and an admin console with persistent audit logs. **Decision support only — not a lending decision.**

> **Data limitation:** trained on the public *Give Me Some Credit* US consumer dataset (2011). It has no Indian, MSME or
> alternative-data (cash-flow, bills) fields. Results do not describe Indian borrowers.

## Quick start
```bash
pip install -r requirements.txt
python3 scripts/create_admin.py --email you@example.com --name "You"     # first admin (prompts for password; never a default account)
cp .env.example .env                                                     # optional: set GROQ_API_KEY / GROQ_MODEL
python3 scripts/serve.py                                                 # http://127.0.0.1:8000  (UI + API)
```
The migrated SQLite database is created automatically at `data/arthsetu.db`. A trained model is included in `models/`.

## Retrain from scratch (needs the Kaggle files)
Put `cs-training.csv` in `data/raw/` (Kaggle → Give Me Some Credit → Data; accept the rules first), then:
```bash
python3 -I scripts/run_phase1.py            # validate, clean, dedupe, stratified 80/20 split, version + manifest
python3 -I backend/ml/training/train.py     # CV model selection on the 80% train set, calibration, threshold, ONE test evaluation
```
## Train the XGBoost model (run on your machine)
```bash
pip install -r requirements-optional.txt                      # xgboost + imbalanced-learn
python3 -I backend/ml/training/train_xgboost.py               # ~10-25 min; --n-iter 40 for a wider search
python3 scripts/serve.py                                      # restart: the app loads the newest model in models/
```
Compares XGBoost plain / scale_pos_weight / SMOTENC (SMOTE only inside training folds, never on the test set), calibrates, picks the
threshold on train CV, scores the 20% test set once, prints the metrics table and saves the artifact the web app loads.
The script's logic was smoke-tested with stand-in packages; XGBoost itself has not been run by the author.

## Tests
```bash
cd backend && python3 -m pytest -q                         # 43 tests: data, features, SMOTE, Shapley, API, auth, RBAC, audit, chat
python3 backend/tests/e2e/run_e2e.py                       # 32 browser checks (needs: python -m playwright install chromium)
```

## Environment variables
See `.env.example`. Required in production: `COOKIE_SECURE=true` (HTTPS). Optional: `GROQ_API_KEY`, `GROQ_MODEL` (use a model id
currently listed by Groq), `ALLOWED_ORIGINS`, `TRUSTED_PROXY`. Without a Groq key the assistant answers from the built-in
knowledge base and says so.

## Deploy (single container / VM)
1. HTTPS reverse proxy (Caddy/nginx) → `python3 scripts/serve.py --host 127.0.0.1 --port 8000` under systemd/Docker.
2. Set `COOKIE_SECURE=true`, `TRUSTED_PROXY=true` (only if the proxy sets `X-Forwarded-For`), persist `data/` and back it up.
3. Run **one** worker: the rate limiter is in-process. For several workers use a shared store and PostgreSQL (see docs/ARCHITECTURE_API.md).

More: `docs/ARCHITECTURE_API.md` (stack, deviations, endpoints), `docs/ML_METHODOLOGY.md` (results + limits), `docs/PROJECT_STATUS.md`.
# ArthSetu_v2
