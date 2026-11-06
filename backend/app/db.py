"""SQLite persistence (stdlib). Versioned SQL migrations; parameterised queries only.
The schema is portable to PostgreSQL (see docs/ARCHITECTURE.md); SQLAlchemy/Alembic were unavailable in the build env."""
from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = [
    ("001_init", """
CREATE TABLE users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'USER' CHECK(role IN ('USER','ADMIN')),
  is_active INTEGER NOT NULL DEFAULT 1,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT);
CREATE TABLE sessions(
  id TEXT PRIMARY KEY,                       -- sha256 of the cookie token (token itself is never stored)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ip TEXT, user_agent TEXT);
CREATE INDEX ix_sessions_user ON sessions(user_id);
CREATE TABLE assessments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  inputs_json TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE INDEX ix_assess_user_created ON assessments(user_id, created_at DESC);
CREATE TABLE prediction_results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL UNIQUE REFERENCES assessments(id) ON DELETE CASCADE,
  model_version TEXT NOT NULL,
  probability REAL NOT NULL CHECK(probability BETWEEN 0 AND 1),
  risk_band TEXT NOT NULL CHECK(risk_band IN ('LOW','MODERATE','HIGH')),
  threshold REAL NOT NULL,
  explanation_json TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE INDEX ix_pred_band ON prediction_results(risk_band);
CREATE INDEX ix_pred_model ON prediction_results(model_version);
CREATE TABLE audit_logs(
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  actor_user_id INTEGER, actor_email TEXT,
  action TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
  outcome TEXT NOT NULL CHECK(outcome IN ('success','failure')),
  ip TEXT, metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX ix_audit_ts ON audit_logs(ts DESC);
CREATE INDEX ix_audit_action ON audit_logs(action);
CREATE TABLE chat_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL);
CREATE TABLE chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX ix_chat_session ON chat_messages(session_id, id);
CREATE TABLE model_versions(
  version TEXT PRIMARY KEY, dataset_version TEXT, algorithm TEXT, metrics_json TEXT, first_loaded_at TEXT NOT NULL);
CREATE TABLE user_preferences(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  theme TEXT NOT NULL DEFAULT 'light' CHECK(theme IN ('light','dark')),
  language TEXT NOT NULL DEFAULT 'en' CHECK(language IN ('en','hi')));
"""),
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def migrate(path: str) -> list[str]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    applied = []
    with connect(path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r[0] for r in c.execute("SELECT name FROM schema_migrations")}
        for name, sql in MIGRATIONS:
            if name not in done:
                c.executescript("BEGIN;" + sql + f"INSERT INTO schema_migrations VALUES('{name}','{iso()}');COMMIT;")
                applied.append(name)
    return applied


@contextlib.contextmanager
def connect(path: str):
    c = sqlite3.connect(path, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
    finally:
        c.close()


_SECRET_KEYS = ("password", "token", "secret", "api_key", "apikey", "authorization", "cookie")


def audit(path: str, action: str, outcome: str = "success", actor: dict | None = None, entity: tuple | None = None,
          ip: str | None = None, meta: dict | None = None, actor_email: str | None = None) -> None:
    """Persist an audit event. Secrets are stripped; callers must not pass financial inputs."""
    safe = {k: v for k, v in (meta or {}).items() if not any(s in k.lower() for s in _SECRET_KEYS)}
    with connect(path) as c:
        c.execute("INSERT INTO audit_logs(id,ts,actor_user_id,actor_email,action,entity_type,entity_id,outcome,ip,metadata_json)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (str(uuid.uuid4()), iso(), actor["id"] if actor else None, actor["email"] if actor else actor_email, action,
                   entity[0] if entity else None, str(entity[1]) if entity else None, outcome, ip, json.dumps(safe, default=str)))
