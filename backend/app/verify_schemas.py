from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VerificationStatus = Literal["VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED"]
ClaimType = Literal["factual", "prediction", "hypothetical", "not_verifiable"]


class VerifyRequest(BaseModel):
    file_id: str
    # Optional: verify only these claims (lets the UI show per-claim progress).
    claim_ids: list[str] | None = None
    # Ignore cached verdicts and verify again (spends Groq tokens).
    refresh: bool = False


# ---------- what the model returns (untrusted, validated) ----------

class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: int  # 1-based index into the evidence list we sent; never a URL
    relevance: str = ""

    @field_validator("source", mode="before")
    @classmethod
    def _idx(cls, v):
        if isinstance(v, str):
            v = v.strip().strip("[]")
        return int(v)

    @field_validator("relevance", mode="before")
    @classmethod
    def _rel(cls, v):
        return str(v).strip()[:500] if v is not None else ""


class RawVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_type: ClaimType = "factual"
    verification_status: VerificationStatus
    explanation: str = Field(min_length=1)
    corrected_claim: str | None = None
    original_value: str | None = None
    corrected_value: str | None = None
    unit: str | None = None
    reference_period: str | None = None
    correction_explanation: str | None = None
    confidence_score: int = 0
    evidence_summary: str = ""
    supporting_sources: list[SourceCitation] = Field(default_factory=list)
    contradicting_sources: list[SourceCitation] = Field(default_factory=list)

    @field_validator("claim_type", mode="before")
    @classmethod
    def _ct(cls, v):
        v = str(v or "factual").strip().lower().replace(" ", "_").replace("-", "_")
        return v if v in {"factual", "prediction", "hypothetical", "not_verifiable"} else "factual"

    @field_validator("verification_status", mode="before")
    @classmethod
    def _status(cls, v):
        return str(v).strip().upper()

    @field_validator("explanation", "evidence_summary", mode="before")
    @classmethod
    def _text(cls, v):
        return str(v).strip()[:2000] if v is not None else ""

    @field_validator("original_value", "corrected_value", "unit", "reference_period", mode="before")
    @classmethod
    def _short(cls, v):
        if v is None or isinstance(v, (dict, list)):
            return None
        v = str(v).strip()
        return v[:200] if v and v.lower() not in {"null", "none", "n/a", "unknown"} else None

    @field_validator("correction_explanation", mode="before")
    @classmethod
    def _cexp(cls, v):
        if not isinstance(v, str):
            return None
        v = v.strip()
        return v[:1500] if v and v.lower() not in {"null", "none", "n/a"} else None

    @field_validator("corrected_claim", mode="before")
    @classmethod
    def _corr(cls, v):
        if not isinstance(v, str):
            return None
        v = v.strip()
        return v[:1000] if v and v.lower() not in {"null", "none", "n/a"} else None

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _conf(cls, v):
        try:
            return max(0, min(100, round(float(v))))
        except (TypeError, ValueError):
            return 0

    @field_validator("supporting_sources", "contradicting_sources", mode="before")
    @classmethod
    def _cites(cls, v):
        return v if isinstance(v, list) else []


# ---------- what we return ----------

class VerdictSource(BaseModel):
    title: str
    url: str
    relevance: str
    domain: str
    source_type: str
    published_date: str | None = None
    snippet: str = ""  # the evidence text as collected from the page (never written by the AI)


# confirmed: the corrected figure appears in a cited source. not_confirmed: the claim is wrong but no reliable
# correction could be established. not_applicable: the claim is not INACCURATE/FALSE.
CorrectionStatus = Literal["confirmed", "not_confirmed", "not_applicable"]


class VerificationResult(BaseModel):
    claim_id: str
    original_claim: str  # copied unchanged from the extracted claim
    pdf_page: int | None = None
    # "completed": a verdict exists. "failed": we could not produce one (verification_status is null).
    check_status: Literal["completed", "failed"] = "completed"
    verification_status: VerificationStatus | None = None
    claim_type: ClaimType = "factual"
    explanation: str = ""
    corrected_claim: str | None = None
    original_value: str | None = None
    corrected_value: str | None = None
    unit: str | None = None
    reference_period: str | None = None
    correction_explanation: str | None = None
    correction_status: CorrectionStatus = "not_applicable"
    confidence_score: int | None = None  # strength of the evidence, not a calibrated probability
    evidence_summary: str = ""
    supporting_sources: list[VerdictSource] = Field(default_factory=list)
    contradicting_sources: list[VerdictSource] = Field(default_factory=list)
    sources_considered: int = 0
    adjustments: list[str] = Field(default_factory=list)  # safety rules applied to the AI's verdict
    cached: bool = False
    error: dict | None = None
    model: str | None = None


class VerifyResponse(BaseModel):
    file_id: str
    total_claims: int
    verified: int
    inaccurate: int
    false: int
    unverified: int
    failed: int
    status: Literal["complete", "partial"]
    results: list[VerificationResult]
    warnings: list[str] = Field(default_factory=list)
