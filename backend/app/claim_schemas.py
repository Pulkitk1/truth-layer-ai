from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaimCategory(str, Enum):
    statistics = "statistics"
    financial = "financial"
    date_timeline = "date_timeline"
    market = "market"
    scientific = "scientific"
    technical = "technical"
    company = "company"
    demographic = "demographic"
    other = "other"


def _clip(v, n):
    return v[:n] if isinstance(v, str) else v


class RawClaim(BaseModel):
    """One claim as returned by the LLM (untrusted; validated and normalised here)."""

    model_config = ConfigDict(extra="ignore")

    claim_text: str = Field(min_length=3)
    normalized_claim: str | None = None
    category: ClaimCategory = ClaimCategory.other
    value: str | None = None
    unit: str | None = None
    time_period: str | None = None
    context: str | None = None
    page_number: int | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, v):
        try:
            return ClaimCategory(str(v).strip().lower())
        except ValueError:
            return ClaimCategory.other

    @field_validator("value", "unit", "time_period", mode="before")
    @classmethod
    def _scalar_to_str(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        if isinstance(v, str):
            v = v.strip()
            return _clip(v, 100) if v and v.lower() not in {"null", "none", "n/a"} else None
        return None

    @field_validator("claim_text", mode="before")
    @classmethod
    def _claim_text(cls, v):
        return _clip(v.strip(), 1000) if isinstance(v, str) else v

    @field_validator("normalized_claim", "context", mode="before")
    @classmethod
    def _long_text(cls, v):
        if not isinstance(v, str):
            return None
        v = v.strip()
        return _clip(v, 1000) or None

    @field_validator("page_number", mode="before")
    @classmethod
    def _page(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None


class LlmClaimsPayload(BaseModel):
    claims: list[dict] = Field(default_factory=list)


class Claim(BaseModel):
    claim_id: str
    claim_text: str
    normalized_claim: str
    category: ClaimCategory
    value: str | None = None
    unit: str | None = None
    time_period: str | None = None
    context: str | None = None
    page_number: int
    verification_status: Literal["pending"] = "pending"


class ClaimsRequest(BaseModel):
    file_id: str


class ClaimsResponse(BaseModel):
    file_id: str
    total_claims: int
    claims: list[Claim]
    status: Literal["complete", "partial"] = "complete"
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
