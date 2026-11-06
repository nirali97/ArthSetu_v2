"""Password hashing (scrypt, stdlib), session tokens, password policy, rate limiter.
Argon2id was requested but argon2-cffi is not installable here; scrypt is an OWASP-listed memory-hard alternative."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque

COMMON = {"password", "password1", "qwerty123", "12345678", "123456789", "1234567890", "iloveyou", "admin123", "welcome1", "letmein123"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,}$")


def hash_password(pw: str, n: int = 2 ** 15, r: int = 8, p: int = 3) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return f"scrypt${n}${r}${p}${b(salt)}${b(h)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=256 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def password_problem(pw: str, email: str = "") -> str | None:
    if len(pw) < 10:
        return "Password must be at least 10 characters."
    if len(pw) > 128:
        return "Password must be at most 128 characters."
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return "Password must contain at least one letter and one digit."
    if pw.lower() in COMMON or (email and pw.lower() == email.lower()):
        return "Password is too common or matches your email."
    return None


def new_token() -> tuple[str, str]:
    t = secrets.token_urlsafe(32)
    return t, hashlib.sha256(t.encode()).hexdigest()


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


class RateLimiter:
    """In-memory sliding window (per process). Use a shared store (e.g. Redis) when running several workers."""

    def __init__(self, enabled: bool = True):
        self.enabled, self._h, self._lock = enabled, defaultdict(deque), threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        if not self.enabled:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._h[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
