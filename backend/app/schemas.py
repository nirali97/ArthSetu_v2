"""Request validation (Pydantic v2). Server-side validation is authoritative; the UI only mirrors it."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.security import EMAIL_RE


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignupIn(_Strict):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v.lower()


class LoginIn(_Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class AssessmentIn(_Strict):
    label: str = Field("", max_length=80)
    revolving_utilization: float = Field(ge=0, le=50)
    age: int = Field(ge=18, le=110)
    past_due_30_59: int = Field(ge=0, le=30)
    past_due_60_89: int = Field(ge=0, le=30)
    past_due_90_plus: int = Field(ge=0, le=30)
    debt_ratio: float = Field(ge=0, le=1000)
    monthly_income: Optional[float] = Field(None, ge=0, le=10_000_000)
    open_credit_lines: int = Field(ge=0, le=60)
    real_estate_loans: int = Field(ge=0, le=60)
    dependents: Optional[int] = Field(None, ge=0, le=20)


class PrefsIn(_Strict):
    theme: Optional[Literal["light", "dark"]] = None
    language: Optional[Literal["en", "hi"]] = None


class ChatIn(_Strict):
    message: str = Field(min_length=1, max_length=1000)
    session_id: Optional[int] = None
    page: Literal["landing", "dashboard", "assess", "result", "history", "model", "settings", "admin"] = "dashboard"
    language: Literal["en", "hi"] = "en"
    risk_band: Optional[Literal["LOW", "MODERATE", "HIGH"]] = None   # only band + factor NAMES are shared as context
    top_factors: list[str] = Field(default_factory=list, max_length=6)


class AdminUserPatch(_Strict):
    role: Optional[Literal["USER", "ADMIN"]] = None
    is_active: Optional[bool] = None
