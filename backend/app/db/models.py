"""Database schema (SQLAlchemy 2.x). Alembic migrations are the only thing that creates it in production."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship

# JSONB on PostgreSQL (indexable), plain JSON elsewhere (the automated tests use SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")

# Deterministic constraint names so migrations are stable and reviewable.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EXTRACTION_STATUSES = ("pending", "success", "partial", "no_text", "failed")
PROCESSING_STATUSES = ("uploaded", "claims_extracted", "evidence_collected", "verified", "report_generated")
JOB_TYPES = ("text_extraction", "claim_extraction", "evidence_search", "verification", "report_generation")
JOB_STATUSES = ("running", "completed", "failed")
REPORT_STATUSES = ("generated", "failed")
FILE_TYPES = ("original_pdf", "generated_report")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=sa.func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=sa.func.now(), nullable=False
    )


class Document(Base):
    """An uploaded PDF. Only metadata lives here; the file itself is in the file store (never in PostgreSQL)."""

    __tablename__ = "documents"
    __table_args__ = (
        sa.CheckConstraint(_in("extraction_status", EXTRACTION_STATUSES), name="extraction_status"),
        sa.CheckConstraint(_in("processing_status", PROCESSING_STATUSES), name="processing_status"),
        sa.CheckConstraint("file_size >= 0", name="file_size"),
        Index("ix_documents_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger)
    total_pages: Mapped[int | None] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    processing_status: Mapped[str] = mapped_column(String(30), default="uploaded", server_default="uploaded")
    storage_key: Mapped[str | None] = mapped_column(String(255))  # set only once the PDF is confirmed in the file store
    access_token_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 of the owner's token (never the token)
    claims_meta: Mapped[dict | None] = mapped_column(JSONType)  # status/warnings/model of the claim extraction run
    summary: Mapped[dict | None] = mapped_column(JSONType)  # cached AI narrative for the report
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    claims: Mapped[list["Claim"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Claim.position", passive_deletes=True
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Report.created_at", passive_deletes=True
    )
    files: Mapped[list["FileObject"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ProcessingJob.created_at", passive_deletes=True
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        sa.UniqueConstraint("document_id", "claim_key", name="uq_claims_document_claim_key"),
        Index("ix_claims_document_position", "document_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    claim_key: Mapped[str] = mapped_column(String(40))  # the id the app and UI use, e.g. "claim_001"
    position: Mapped[int] = mapped_column(Integer)
    original_claim: Mapped[str] = mapped_column(Text)
    normalized_claim: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other", server_default="other")
    value: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(100))
    time_period: Mapped[str | None] = mapped_column(String(100))
    context: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    # State of the evidence search for this claim (the evidence rows themselves are in `evidence`).
    search_status: Mapped[str | None] = mapped_column(String(20))
    search_query: Mapped[str | None] = mapped_column(Text)
    query_source: Mapped[str | None] = mapped_column(String(20))
    search_error: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created()

    document: Mapped[Document] = relationship(back_populates="claims")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Evidence.position", passive_deletes=True
    )
    verification: Mapped["Verification | None"] = relationship(
        back_populates="claim", cascade="all, delete-orphan", uselist=False, passive_deletes=True
    )


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_source_domain", "source_domain"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # rank order as returned by the search
    source_title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20), default="web", server_default="web")
    content: Mapped[str] = mapped_column(Text)  # untrusted web snippet
    published_date: Mapped[str | None] = mapped_column(String(40))  # as reported by the source; formats vary
    relevance_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _created()

    claim: Mapped[Claim] = relationship(back_populates="evidence")


class Verification(Base):
    """At most one verdict per claim (re-verifying replaces it)."""

    __tablename__ = "verifications"
    __table_args__ = (
        sa.CheckConstraint(
            "verification_status IS NULL OR " + _in("verification_status", ("VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED")),
            name="verification_status",
        ),
        sa.CheckConstraint("confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)", name="confidence_score"),
        Index("ix_verifications_status", "verification_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), unique=True)
    verification_status: Mapped[str | None] = mapped_column(String(20))
    claim_type: Mapped[str] = mapped_column(String(20), default="factual", server_default="factual")
    explanation: Mapped[str] = mapped_column(Text, default="", server_default="")
    corrected_claim: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[int | None] = mapped_column(Integer)  # evidence strength 0-100, not a probability
    evidence_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    fingerprint: Mapped[str | None] = mapped_column(String(64))  # what the verdict was based on (claim+model+evidence)
    evidence_hash: Mapped[str | None] = mapped_column(String(64))  # same, ignoring the model; detects stale verdicts
    details: Mapped[dict] = mapped_column(JSONType)  # full result incl. cited sources and applied safety rules
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    claim: Mapped[Claim] = relationship(back_populates="verification")


class Report(Base):
    """Metadata of a generated PDF report. The PDF itself is in the file store."""

    __tablename__ = "reports"
    __table_args__ = (sa.CheckConstraint(_in("status", REPORT_STATUSES), name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="generated", server_default="generated")
    storage_key: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created()

    document: Mapped[Document] = relationship(back_populates="reports")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        sa.CheckConstraint(_in("job_type", JOB_TYPES), name="job_type"),
        sa.CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        Index("ix_processing_jobs_document_type", "document_id", "job_type"),
        Index("ix_processing_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="running", server_default="running")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    document: Mapped[Document] = relationship(back_populates="jobs")


class FileObject(Base):
    """A stored PDF (the original upload or a generated report). The bytes live in PostgreSQL (BYTEA).

    Deleting the document deletes its files in the same transaction (ON DELETE CASCADE). For an original PDF `id` is
    random; for a generated report `id` equals the report's id. `file_content` is deferred so listing or counting files
    never pulls the bytes over the network."""

    __tablename__ = "file_objects"
    __table_args__ = (
        sa.CheckConstraint(_in("file_type", FILE_TYPES), name="file_type"),
        sa.CheckConstraint("mime_type = 'application/pdf'", name="mime_type"),
        sa.CheckConstraint("file_size > 0", name="file_size"),
        sa.UniqueConstraint("document_id", "file_type", "checksum", name="uq_file_objects_document_type_checksum"),  # no duplicate copies
        Index("ix_file_objects_document_type", "document_id", "file_type"),
        # at most one original PDF per document
        Index("uq_file_objects_one_original", "document_id", unique=True, postgresql_where=sa.text("file_type = 'original_pdf'"), sqlite_where=sa.text("file_type = 'original_pdf'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    file_type: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf", server_default="application/pdf")
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    checksum: Mapped[str] = mapped_column(String(64))  # SHA-256 of file_content, verified every time the file is read
    created_at: Mapped[datetime] = _created()

    document: Mapped[Document] = relationship(back_populates="files")
