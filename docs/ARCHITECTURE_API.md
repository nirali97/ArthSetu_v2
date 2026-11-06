# Architecture & API

## Stack actually used (and why it differs from the brief)
| Brief | Used | Reason |
|---|---|---|
| FastAPI | **Starlette** + Pydantic v2 | FastAPI/SQLAlchemy/Alembic/argon2/groq SDK were not installable where this was built; Starlette is what FastAPI wraps. Handlers are plain async functions. |
| PostgreSQL + SQLAlchemy + Alembic | **SQLite** (stdlib) + SQL migrations (`schema_migrations`) | Same relational schema (FKs, CHECKs, indexes); portable to PostgreSQL. **Not run on PostgreSQL.** |
| Argon2id | **scrypt** (N=2^15, r=8, p=3, per-user salt) | OWASP-listed memory-hard KDF; stdlib. |
| React + Vite + TS + Tailwind + shadcn + Recharts | **Dependency-free JS SPA** served by the API | npm unavailable. DOM built with `textContent` (no HTML injection); charts are CSS/SVG. |
| Groq SDK | Groq REST via `urllib` | Same API, no dependency. |

## Security model
Server-side sessions (random 256-bit token; only its SHA-256 stored); cookie `HttpOnly; SameSite=Lax; Secure` (when `COOKIE_SECURE=true`); absolute (12h) + idle (2h) expiry;
logout destroys the session; deactivation revokes sessions immediately. CSRF: required `X-Requested-With: ArthSetu` header + Origin check on all state-changing API calls.
Roles are read from the database on every request (`USER`/`ADMIN`); no client-supplied role is ever trusted (`extra=forbid`). First admin only via `scripts/create_admin.py`.
Lockout after 5 failed logins (15 min), per-IP/user rate limits, identical error for unknown user vs wrong password, CSP + security headers, parameterised SQL, generic 500s,
audit log with secret-stripping (no passwords, tokens or financial inputs). The Groq key never leaves the server; the assistant receives only the question, page, risk band and whitelisted factor names.

## Tables
users, sessions, assessments, prediction_results, audit_logs, chat_sessions, chat_messages, model_versions, user_preferences (role is a CHECK-constrained column, not a table).

## Endpoints (JSON; errors: `{"error":{"code","message","details":[{field,message}]}}`)
Public: `GET /api/health`, `GET /api/features`, `POST /api/auth/signup|login|logout`.
User (session): `GET /api/auth/me`, `PATCH /api/me/preferences`, `POST /api/assessments`, `GET /api/assessments?q&band&page&page_size`, `GET /api/assessments/{id}` (incl. stored explanation),
`GET /api/assessments/export.csv`, `GET /api/dashboard`, `GET /api/model`, `POST /api/chat`, `GET /api/chat/history`, `DELETE /api/chat/{id}`.
Admin (ADMIN only, 403 otherwise): `GET /api/admin/overview|users|audit|predictions|system`, `PATCH /api/admin/users/{id}` (role / is_active; cannot change self).
Status codes: 200/201, 400 bad JSON, 401 unauthenticated/expired, 403 forbidden/CSRF, 404, 409 duplicate email, 422 validation, 429 rate/lockout, 500 generic, 503 model unavailable.

## Known gaps
Rate limiter is per-process (use Redis for multi-worker). SQLite → PostgreSQL migration not exercised. No email verification / password reset / MFA.
Frontend is not React/TS and has no unit-test framework; coverage is the Playwright E2E script. Hindi strings were written by the assistant and not reviewed by a native speaker.
Groq live calls were not tested (no key/network here): the request code is exercised only through mocks and the failure/fallback path.
