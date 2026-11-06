"""Settings from environment variables (see .env.example). No secrets live in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    db_path: str = ""
    models_dir: str = ""
    frontend_dir: str = ""
    session_ttl_hours: float = 12.0
    idle_timeout_minutes: float = 120.0
    cookie_secure: bool = False          # set COOKIE_SECURE=true behind HTTPS (required in production)
    allowed_origins: list = field(default_factory=list)
    groq_api_key: str = ""
    groq_model: str = ""
    groq_url: str = "https://api.groq.com/openai/v1/chat/completions"
    rate_limits_enabled: bool = True
    scrypt_n: int = 2 ** 15
    trusted_proxy: bool = False

    @classmethod
    def from_env(cls, **over) -> "Settings":
        e = os.environ.get
        s = cls(
            db_path=e("DATABASE_PATH", str(ROOT / "data" / "arthsetu.db")),
            models_dir=e("MODELS_DIR", str(ROOT / "models")),
            frontend_dir=e("FRONTEND_DIR", str(ROOT / "frontend")),
            session_ttl_hours=float(e("SESSION_TTL_HOURS", "12")),
            idle_timeout_minutes=float(e("SESSION_IDLE_MINUTES", "120")),
            cookie_secure=_bool(e("COOKIE_SECURE"), False),
            allowed_origins=[o.strip() for o in e("ALLOWED_ORIGINS", "").split(",") if o.strip()],
            groq_api_key=e("GROQ_API_KEY", ""),
            groq_model=e("GROQ_MODEL", ""),
            rate_limits_enabled=_bool(e("RATE_LIMITS_ENABLED"), True),
            trusted_proxy=_bool(e("TRUSTED_PROXY"), False),
        )
        for k, v in over.items():
            setattr(s, k, v)
        return s
