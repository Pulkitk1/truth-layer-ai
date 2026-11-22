from typing import Literal

from pydantic import BaseModel, Field

SearchStatus = Literal["completed", "no_results", "failed", "skipped"]
SourceType = Literal["government", "institution", "research", "news", "reference", "web", "community"]


class SearchRequest(BaseModel):
    file_id: str
    # Optional: search only these claims (lets the UI show per-claim progress).
    claim_ids: list[str] | None = None
    # Ignore cached results and search again (spends Tavily credits).
    refresh: bool = False


class Source(BaseModel):
    title: str
    url: str
    content: str  # untrusted snippet from the web; never proof on its own
    published_date: str | None = None
    score: float | None = None
    domain: str
    source_type: SourceType = "web"
    claim_id: str


class SearchError(BaseModel):
    code: str
    message: str


class ClaimSearchResult(BaseModel):
    claim_id: str
    claim_text: str
    page_number: int | None = None
    search_status: SearchStatus
    search_query: str | None = None
    query_source: Literal["ai", "rule_based"] | None = None
    sources: list[Source] = Field(default_factory=list)
    sources_found: int = 0
    cached: bool = False
    error: SearchError | None = None
    verification_status: Literal["pending"] = "pending"


class SearchResponse(BaseModel):
    file_id: str
    total_claims: int
    total_sources_found: int
    status: Literal["complete", "partial"]
    search_depth: str
    claims: list[ClaimSearchResult]
    warnings: list[str] = Field(default_factory=list)
