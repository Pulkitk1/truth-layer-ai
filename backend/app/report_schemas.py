from typing import Literal

from pydantic import BaseModel, Field

from .search_schemas import Source
from .verify_schemas import VerificationResult

ReportStatus = Literal["VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED", "PENDING"]


class ReportClaim(BaseModel):
    """One claim with everything known about it: extraction, collected evidence and verdict."""

    claim_id: str
    claim_text: str
    normalized_claim: str
    category: str
    value: str | None = None
    unit: str | None = None
    time_period: str | None = None
    context: str | None = None
    page_number: int
    # PENDING = no (current) verdict exists yet.
    status: ReportStatus
    confidence_score: int | None = None
    supporting_count: int = 0
    contradicting_count: int = 0
    search_status: str | None = None
    search_query: str | None = None
    collected_sources: list[Source] = Field(default_factory=list)
    verification: VerificationResult | None = None
    stale: bool = False  # the evidence changed after this verdict was produced


class ReportCounts(BaseModel):
    total: int
    verified: int
    inaccurate: int
    false: int
    unverified: int
    pending: int


class CategoryCount(BaseModel):
    category: str
    count: int


class InvestigationItem(BaseModel):
    claim_id: str
    claim_text: str
    status: ReportStatus
    reason: str


class ReportSummary(BaseModel):
    # Built by code from the stored verdicts: always present and always matches the counts.
    text: str
    needs_investigation: list[InvestigationItem] = Field(default_factory=list)
    # Optional plain-language narrative written by the AI from the same verdicts.
    narrative: str | None = None
    narrative_error: str | None = None
    narrative_model: str | None = None


class Report(BaseModel):
    file_id: str
    document_name: str
    stage: Literal["claims_extracted", "evidence_collected", "verified"]
    counts: ReportCounts
    categories: list[CategoryCount]
    claims: list[ReportClaim]
    summary: ReportSummary
    warnings: list[str] = Field(default_factory=list)
    # The PDF report can be downloaded once every claim has a current verdict.
    pdf_ready: bool = False
    pdf_blocker: str | None = None
