"""Reads and writes the database rows behind the app's existing result shapes.

The services (claims, search, verify, report) exchange plain dicts: {claims}, {queries, results},
{results: {fp, ev, result}}, {fp, narrative}. This module maps those dicts to and from the normalised tables,
so the services keep working unchanged while the data is persistent. Writes are upserts and never remove
rows that are absent from the dict (so two workers cannot erase each other's results); removal is explicit."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from . import config, filestore
from .db.models import Claim, Document, Evidence, ProcessingJob, Report, Verification
from .db.session import session_scope

_RANK = {"uploaded": 0, "claims_extracted": 1, "evidence_collected": 2, "verified": 3, "report_generated": 4}


def _uid(file_id: str) -> uuid.UUID:
    return uuid.UUID(hex=file_id)


def _doc(s: Session, file_id: str) -> Document | None:
    return s.get(Document, _uid(file_id))


def _advance(doc: Document, stage: str) -> None:
    if _RANK[stage] > _RANK[doc.processing_status]:
        doc.processing_status = stage


def _claims(s: Session, doc_id: uuid.UUID) -> dict[str, Claim]:
    rows = s.scalars(select(Claim).where(Claim.document_id == doc_id).options(selectinload(Claim.evidence)))
    return {c.claim_key: c for c in rows}


# ---------- documents ----------

def create_document(
    file_id: str, filename: str, size: int, storage_key: str | None, token_hash: str | None = None, data: bytes | None = None
) -> None:
    """Create a document. With `data`, its PDF is stored in the SAME transaction: both are saved, or neither is."""
    with session_scope() as s:
        doc = Document(id=_uid(file_id), filename=filename[:255], file_size=size, storage_key=storage_key, access_token_hash=token_hash)
        s.add(doc)
        if data is not None:
            s.flush()  # the file row refers to the document row
            key = filestore.document_key(file_id)
            filestore.get_store().put(s, key, doc.id, filename, data)
            doc.storage_key = key


def get_access(file_id: str) -> tuple[bool, str | None]:
    """(document exists, stored token hash). Documents from before access tokens existed have no hash."""
    with session_scope() as s:
        row = s.execute(select(Document.access_token_hash).where(Document.id == _uid(file_id))).first()
        return (False, None) if row is None else (True, row[0])


def set_storage_key(file_id: str, key: str) -> None:
    with session_scope() as s:
        if (d := _doc(s, file_id)) is not None:
            d.storage_key = key


def get_document(file_id: str) -> dict | None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return None
        return {
            "filename": d.filename,
            "size": d.file_size,
            "total_pages": d.total_pages,
            "extraction_status": d.extraction_status,
            "processing_status": d.processing_status,
            "storage_key": d.storage_key,
            "created_at": d.created_at,
        }


def mark_extracted(file_id: str, total_pages: int | None, status: str) -> None:
    with session_scope() as s:
        if (d := _doc(s, file_id)) is not None:
            d.total_pages, d.extraction_status = total_pages, status


def mark_extraction_failed(file_id: str) -> None:
    with session_scope() as s:
        if (d := _doc(s, file_id)) is not None:
            d.extraction_status = "failed"


def delete_document(file_id: str) -> bool:
    """Delete a document row; claims, evidence, verdicts, reports and jobs go with it (ON DELETE CASCADE)."""
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return False
        s.delete(d)
        return True


def has_active_job(file_id: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.active_job_minutes())
    with session_scope() as s:
        return bool(
            s.scalar(
                select(func.count()).select_from(ProcessingJob).where(
                    ProcessingJob.document_id == _uid(file_id), ProcessingJob.status == "running", ProcessingJob.updated_at > cutoff
                )
            )
        )


def expired_documents(days: int) -> list[str]:
    """Documents older than `days` that no recent running job is using."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    busy = datetime.now(timezone.utc) - timedelta(minutes=config.active_job_minutes())
    active = select(ProcessingJob.document_id).where(ProcessingJob.status == "running", ProcessingJob.updated_at > busy)
    with session_scope() as s:
        return [i.hex for i in s.scalars(select(Document.id).where(Document.created_at < cutoff, Document.id.not_in(active)))]


def count_jobs(file_id: str, job_type: str, minutes: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with session_scope() as s:
        return s.scalar(
            select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.document_id == _uid(file_id), ProcessingJob.job_type == job_type, ProcessingJob.created_at > since
            )
        ) or 0


def report_storage_key(file_id: str, report_id: str) -> tuple[bool, str | None, str | None]:
    """(report exists for this document, storage key, filename)."""
    with session_scope() as s:
        r = s.scalar(select(Report).where(Report.id == _uid(report_id), Report.document_id == _uid(file_id)))
        return (False, None, None) if r is None else (True, r.storage_key, r.filename)


# ---------- claims ----------

def save_claims(file_id: str, data: dict) -> None:
    """Replace the document's claims (a new extraction invalidates evidence and verdicts, which cascade away)."""
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return
        s.execute(delete(Claim).where(Claim.document_id == d.id))
        s.expire(d, ["claims"])
        for i, c in enumerate(data.get("claims") or [], start=1):
            s.add(
                Claim(
                    document_id=d.id,
                    claim_key=c["claim_id"],
                    position=i,
                    original_claim=c["claim_text"],
                    normalized_claim=c.get("normalized_claim"),
                    category=c.get("category") or "other",
                    value=c.get("value"),
                    unit=c.get("unit"),
                    time_period=c.get("time_period"),
                    context=c.get("context"),
                    page_number=c.get("page_number"),
                )
            )
        d.claims_meta = {k: v for k, v in data.items() if k not in ("claims", "file_id", "total_claims")}
        d.processing_status = "claims_extracted"


def load_claims(file_id: str) -> dict | None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None or d.claims_meta is None:
            return None
        rows = s.scalars(select(Claim).where(Claim.document_id == d.id).order_by(Claim.position)).all()
        claims = [
            {
                "claim_id": c.claim_key,
                "claim_text": c.original_claim,
                "normalized_claim": c.normalized_claim,
                "category": c.category,
                "value": c.value,
                "unit": c.unit,
                "time_period": c.time_period,
                "context": c.context,
                "page_number": c.page_number,
            }
            for c in rows
        ]
        return {"file_id": file_id, "total_claims": len(claims), "claims": claims, **d.claims_meta}


# ---------- evidence (the web search) ----------

def save_search(file_id: str, cache: dict) -> None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return
        by_key = _claims(s, d.id)
        for key, q in (cache.get("queries") or {}).items():
            if (c := by_key.get(key)) is not None:
                c.search_query, c.query_source = q.get("query"), q.get("source")
        collected = False
        for key, r in (cache.get("results") or {}).items():
            c = by_key.get(key)
            if c is None or not r.get("search_status"):
                continue
            c.search_status = r["search_status"]
            c.search_query = r.get("search_query") or c.search_query
            c.query_source = r.get("query_source") or c.query_source
            c.search_error = r.get("error")
            c.evidence = [
                Evidence(
                    position=i,
                    source_title=src.get("title") or src["domain"],
                    source_url=src["url"],
                    source_domain=src["domain"],
                    source_type=src.get("source_type") or "web",
                    content=src.get("content") or "",
                    published_date=src.get("published_date"),
                    relevance_score=src.get("score"),
                )
                for i, src in enumerate(r.get("sources") or [])
            ]
            collected = True
        if collected:
            _advance(d, "evidence_collected")


def load_search(file_id: str) -> dict | None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return None
        queries, results = {}, {}
        for key, c in _claims(s, d.id).items():
            if c.search_query is not None:
                queries[key] = {"query": c.search_query, "source": c.query_source}
            if c.search_status is not None:
                sources = [
                    {
                        "title": e.source_title,
                        "url": e.source_url,
                        "content": e.content,
                        "published_date": e.published_date,
                        "score": e.relevance_score,
                        "domain": e.source_domain,
                        "source_type": e.source_type,
                        "claim_id": key,
                    }
                    for e in c.evidence
                ]
                results[key] = {
                    "claim_id": key,
                    "claim_text": c.original_claim,
                    "page_number": c.page_number,
                    "search_status": c.search_status,
                    "search_query": c.search_query,
                    "query_source": c.query_source,
                    "sources": sources,
                    "sources_found": len(sources),
                    "cached": False,
                    "error": c.search_error,
                    "verification_status": "pending",
                }
        if not queries and not results:
            return None
        return {"queries": queries, "results": results}


def delete_search(file_id: str) -> None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return
        for c in _claims(s, d.id).values():
            c.search_status = c.search_query = c.query_source = c.search_error = None
            c.evidence = []


# ---------- verdicts ----------

def save_verify(file_id: str, data: dict) -> None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return
        by_key = _claims(s, d.id)
        existing = {v.claim_id: v for v in s.scalars(select(Verification).where(Verification.claim_id.in_([c.id for c in by_key.values()])))}
        for key, entry in (data.get("results") or {}).items():
            c, r = by_key.get(key), entry.get("result")
            if c is None or not isinstance(r, dict):
                continue
            v = existing.get(c.id) or Verification(claim_id=c.id)
            v.verification_status = r.get("verification_status")
            v.claim_type = r.get("claim_type") or "factual"
            v.explanation = r.get("explanation") or ""
            v.corrected_claim = r.get("corrected_claim")
            v.confidence_score = r.get("confidence_score")
            v.evidence_summary = r.get("evidence_summary") or ""
            v.fingerprint, v.evidence_hash = entry.get("fp"), entry.get("ev")
            v.details = r
            s.add(v)
        s.flush()
        total = s.scalar(select(func.count()).select_from(Claim).where(Claim.document_id == d.id)) or 0
        done = s.scalar(select(func.count()).select_from(Verification).join(Claim).where(Claim.document_id == d.id)) or 0
        if total and done >= total:
            _advance(d, "verified")


def load_verify(file_id: str) -> dict | None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return None
        rows = s.execute(
            select(Claim.claim_key, Verification).join(Verification, Verification.claim_id == Claim.id).where(Claim.document_id == d.id)
        ).all()
        if not rows:
            return None
        return {"results": {key: {"fp": v.fingerprint, "ev": v.evidence_hash, "result": v.details} for key, v in rows}}


def delete_verify(file_id: str) -> None:
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is not None:
            ids = select(Claim.id).where(Claim.document_id == d.id)
            s.execute(delete(Verification).where(Verification.claim_id.in_(ids)))


# ---------- AI summary ----------

def save_summary(file_id: str, data: dict) -> None:
    with session_scope() as s:
        if (d := _doc(s, file_id)) is not None:
            d.summary = data


def load_summary(file_id: str) -> dict | None:
    with session_scope() as s:
        d = _doc(s, file_id)
        return d.summary if d is not None else None


def delete_summary(file_id: str) -> None:
    save_summary(file_id, None)  # type: ignore[arg-type]


# ---------- reports ----------

def add_report(
    file_id: str,
    filename: str,
    storage_key: str | None,
    size: int | None,
    status: str = "generated",
    report_id: str | None = None,
    data: bytes | None = None,
) -> str | None:
    """Record a generated report. With `data`, the PDF is stored in the same transaction as its metadata. If this
    document already holds an identical PDF, nothing new is stored and the existing report's id is returned."""
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            return None
        if data is not None:
            report_id = report_id or uuid.uuid4().hex
            storage_key = filestore.report_key(report_id)
            file_id_, created = filestore.get_store().put(s, storage_key, d.id, filename, data)
            if not created:
                return file_id_.hex  # the same file is already stored (its id is the earlier report's id)
            size = len(data)
        r = Report(id=_uid(report_id) if report_id else uuid.uuid4(), document_id=d.id, filename=filename[:255], status=status, storage_key=storage_key, file_size=size)
        s.add(r)
        if status == "generated":
            _advance(d, "report_generated")
        s.flush()
        return r.id.hex


def new_report_id() -> str:
    return uuid.uuid4().hex


def list_reports(file_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Report).where(Report.document_id == _uid(file_id)).order_by(Report.created_at))
        return [
            {"id": r.id.hex, "filename": r.filename, "status": r.status, "file_size": r.file_size, "created_at": r.created_at, "has_file": r.storage_key is not None}
            for r in rows
        ]


# ---------- processing jobs ----------

def _safe_error(exc: BaseException) -> str:
    """A short, document-free description of why a job failed (codes and messages we wrote, or just the type)."""
    detail = getattr(exc, "detail", None)  # fastapi HTTPException
    code = getattr(exc, "code", None) or (detail.get("code") if isinstance(detail, dict) else None)
    message = getattr(exc, "message", None) or (detail.get("message") if isinstance(detail, dict) else None)
    return (f"{code}: {message}" if code and message else type(exc).__name__)[:500]


@contextmanager
def track_job(file_id: str, job_type: str):
    """Record a processing step (running -> completed/failed) against the document it belongs to."""
    with session_scope() as s:
        d = _doc(s, file_id)
        if d is None:
            job_id = None
        else:
            job = ProcessingJob(document_id=d.id, job_type=job_type, status="running")
            s.add(job)
            s.flush()
            job_id = job.id
    try:
        yield
    except BaseException as exc:
        _finish_job(job_id, "failed", _safe_error(exc))
        raise
    _finish_job(job_id, "completed", None)


def _finish_job(job_id: uuid.UUID | None, status: str, error: str | None) -> None:
    if job_id is None:
        return
    try:
        with session_scope() as s:
            if (job := s.get(ProcessingJob, job_id)) is not None:
                job.status, job.error_message = status, error
    except Exception:  # never let bookkeeping hide the real result or error
        pass


def list_jobs(file_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(ProcessingJob).where(ProcessingJob.document_id == _uid(file_id)).order_by(ProcessingJob.created_at))
        return [{"id": j.id.hex, "job_type": j.job_type, "status": j.status, "error_message": j.error_message} for j in rows]
