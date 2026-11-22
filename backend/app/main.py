import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from . import auth, config, db, filestore, readiness, repository, storage
from . import claims as claims_service
from . import pdf_report as pdf_service
from . import report as report_service
from . import search as search_service
from . import verify as verify_service
from .claim_schemas import ClaimsRequest, ClaimsResponse
from .config import CORS_ORIGINS, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from .db import DbError
from .extraction import PdfError, extract_pdf
from .filestore import StorageError
from .llm import LlmError
from .middleware import rate_limit_and_headers
from .report_schemas import Report
from .schemas import ExtractRequest, ExtractResponse, UploadResponse
from .search_schemas import SearchRequest, SearchResponse
from .tavily_client import TavilyError
from .verify_schemas import VerifyRequest, VerifyResponse

CHUNK = 1024 * 1024
logger = logging.getLogger("truthlayer")


def _sweep() -> None:
    """Housekeeping: delete expired documents (their stored PDFs go with them)."""
    storage.purge_expired()


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(config.retention_sweep_minutes() * 60)
        try:
            await run_in_threadpool(_sweep)
        except Exception as exc:  # database or storage down: try again next time
            logger.warning("retention sweep skipped: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await run_in_threadpool(_sweep)
    except Exception as exc:  # an unreachable database or bucket must not stop the API from starting (see /api/health)
        logger.warning("startup cleanup skipped: %s", type(exc).__name__)
    task = asyncio.create_task(_retention_loop())
    yield
    task.cancel()
    db.dispose_engine()


_docs = config.app_env() != "production"  # no public API explorer in production
app = FastAPI(
    title="TruthLayer AI API",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs else None,
)
# Order matters: the last middleware added is the outermost. CORS goes last so that even rate-limit and error
# responses carry the CORS headers the browser needs to show them.
app.middleware("http")(rate_limit_and_headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # an explicit list, never "*"
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],  # lets the browser read the PDF's suggested filename
)


def err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _json_error(exc) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})


@app.exception_handler(PdfError)
async def pdf_error_handler(_, exc: PdfError):
    return _json_error(exc)


@app.exception_handler(LlmError)
async def llm_error_handler(_, exc: LlmError):
    return _json_error(exc)


@app.exception_handler(TavilyError)
async def tavily_error_handler(_, exc: TavilyError):
    return _json_error(exc)


@app.exception_handler(DbError)
async def db_error_handler(_, exc: DbError):
    return _json_error(exc)


@app.exception_handler(StorageError)
async def storage_error_handler(_, exc: StorageError):
    return _json_error(exc)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, exc: RequestValidationError):
    # Name the offending fields, but never echo the submitted values back.
    fields = sorted({".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]) for e in exc.errors()})
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "invalid_request", "message": "The request was not valid: check " + ", ".join(fields) + ".", "fields": fields}},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)  # no details: they may hold document text
    return JSONResponse(status_code=500, content={"detail": {"code": "internal_error", "message": "Something went wrong on the server. Please try again."}})


@app.get("/healthz")
def liveness():
    """Is the process up? Deliberately does not touch the database or storage, so a platform health probe that calls it
    every few seconds does not keep Neon awake (use /api/health for the full check)."""
    return {"status": "ok"}


@app.get("/api/health")
def health():
    """Backend, database, schema, storage and production-readiness status. Never includes credentials or secrets."""
    database = db.check_database()
    storage_status = filestore.status()
    ready = readiness.evaluate(database, storage_status)
    storage_ok = bool(storage_status.get("reachable"))
    ok = database["status"] == "ok" and storage_ok
    body = {
        "status": "ok" if ok else "degraded",
        "backend": "ok",
        "database": database,
        "schema": {"status": database.get("schema", "unknown"), "revision": database.get("revision")},
        "storage": storage_status,
        "environment": config.app_env(),
        "production_ready": ready["production_ready"],
        "checks": ready["checks"],
        "blockers": ready["blockers"],
        "max_upload_mb": MAX_UPLOAD_MB,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    name = (file.filename or "").strip()
    if not name.lower().endswith(".pdf"):
        raise err(400, "invalid_file_type", "Only .pdf files are accepted.")

    file_id = storage.new_file_id()
    buf = bytearray()
    while chunk := await file.read(CHUNK):  # the size limit is checked while reading, before anything is saved
        buf += chunk
        if len(buf) > MAX_UPLOAD_BYTES:
            raise err(413, "file_too_large", f"File exceeds the {MAX_UPLOAD_MB} MB limit.")
    if not buf:
        raise err(400, "empty_file", "The uploaded file is empty.")
    if b"%PDF-" not in bytes(buf[:1024]):
        raise err(400, "invalid_pdf", "File content is not a valid PDF.")
    data = bytes(buf)
    del buf

    safe_name = name.replace("\\", "/").split("/")[-1][:255]
    token = auth.new_token()  # shown to the uploader once; only its hash is stored
    # One transaction: the document row and its PDF (with checksum) are saved together, or the upload fails.
    await run_in_threadpool(storage.save_meta, file_id, safe_name, len(data), auth.hash_token(token), data)
    return UploadResponse(
        file_id=file_id, filename=safe_name, file_size=len(data), upload_status="uploaded", access_token=token
    )


@app.post("/api/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest, authorization: str | None = Header(default=None)):
    meta = auth.authorize(req.file_id, authorization)
    with repository.track_job(req.file_id, "text_extraction"):
        return _extract_text(req.file_id, meta["filename"])


def _extract_text(file_id: str, filename: str):
    """Run the PDF text extraction and record its outcome on the document."""
    data = storage.load_pdf(file_id)  # read from the database; raises StorageError if it fails its checksum
    if data is None:
        raise err(404, "file_not_found", "The original PDF is no longer stored. Please upload it again.")
    try:
        result = extract_pdf(data, file_id, filename)
    except PdfError:
        repository.mark_extraction_failed(file_id)
        raise
    repository.mark_extracted(file_id, result.total_pages, result.extraction_status)
    return result


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str, authorization: str | None = Header(default=None)):
    auth.authorize(file_id, authorization)
    if not storage.delete(file_id):  # raises StorageError (503) and keeps the document if a stored file cannot be removed
        raise err(404, "file_not_found", "File not found.")
    return {"status": "deleted"}


@app.post("/api/claims/extract", response_model=ClaimsResponse)
def extract_claims(req: ClaimsRequest, authorization: str | None = Header(default=None)):
    meta = auth.authorize(req.file_id, authorization)
    limit = config.max_claim_extractions_per_hour()
    if repository.count_jobs(req.file_id, "claim_extraction", 60) >= limit:  # each run spends Groq credits
        raise err(429, "extraction_limit_reached", f"Claims were already extracted from this document {limit} times in the last hour. Try again later.")
    with repository.track_job(req.file_id, "claim_extraction"):
        # Reuse the existing PDF text extraction (raises PdfError for corrupted/protected files).
        extraction = _extract_text(req.file_id, meta["filename"])
        result = claims_service.extract_claims(req.file_id, extraction.pages)
    # Remember the extracted claims so the web-search step can use them without
    # re-running (and re-paying for) the AI. New claims invalidate old search results.
    storage.save_json(req.file_id, "claims", result.model_dump(mode="json"))
    storage.delete_json(req.file_id, "search")
    storage.delete_json(req.file_id, "verify")
    storage.delete_json(req.file_id, "summary")
    return result


@app.post("/api/claims/search", response_model=SearchResponse)
def search_claims(req: SearchRequest, authorization: str | None = Header(default=None)):
    auth.authorize(req.file_id, authorization)
    saved = storage.load_json(req.file_id, "claims")
    if saved is None:
        raise err(409, "claims_not_extracted", "Extract claims with AI first, then search the web for evidence.")
    with repository.track_job(req.file_id, "evidence_search"):
        return search_service.search_claims(req, saved["claims"])


@app.post("/api/claims/verify", response_model=VerifyResponse)
def verify_claims(req: VerifyRequest, authorization: str | None = Header(default=None)):
    auth.authorize(req.file_id, authorization)
    saved = storage.load_json(req.file_id, "claims")
    if saved is None:
        raise err(409, "claims_not_extracted", "Extract claims with AI first.")
    with repository.track_job(req.file_id, "verification"):
        return verify_service.verify_claims(req, saved["claims"])


def _load_report(file_id: str, authorization: str | None) -> Report:
    meta = auth.authorize(file_id, authorization)
    saved = storage.load_json(file_id, "claims")
    if saved is None:
        raise err(409, "claims_not_extracted", "No claims have been extracted for this document yet.")
    return report_service.build_report(file_id, saved["claims"], meta["filename"])


@app.get("/api/reports/{file_id}", response_model=Report)
def get_report(file_id: str, authorization: str | None = Header(default=None)):
    """Everything the results dashboard needs, computed from the saved backend results."""
    return _load_report(file_id, authorization)


@app.post("/api/reports/{file_id}/summary", response_model=Report)
def generate_summary(file_id: str, refresh: bool = False, authorization: str | None = Header(default=None)):
    """Adds an AI-written narrative summary (cached). Falls back to the built-in summary if the AI fails."""
    return report_service.add_narrative(_load_report(file_id, authorization), file_id, refresh)


def _record_report(file_id: str, filename: str, pdf: bytes) -> None:
    """Save the generated PDF and its metadata in one transaction. The user's download does not depend on it: if the
    copy cannot be saved, the failure is logged by type only and the PDF is still returned."""
    try:
        repository.add_report(file_id, filename, None, len(pdf), data=pdf)
    except (StorageError, DbError) as exc:
        logger.error("could not store the generated report: %s", type(exc).__name__)


@app.get("/api/report/{file_id}")
def download_report(file_id: str, authorization: str | None = Header(default=None)):
    """Download the fact-checking report as a PDF.

    Built only from the saved claims, evidence and verdicts: Groq and Tavily are never called here.
    The PDF is generated in memory and streamed back, so no temporary file is left behind.
    """
    if not storage.is_valid_id(file_id):
        raise err(400, "invalid_file_id", "That is not a valid report id.")
    report = _load_report(file_id, authorization)  # 401/403/404 if not the owner, 409 if no claims were extracted
    if not report.pdf_ready:
        raise err(409, "verification_incomplete", report.pdf_blocker or "Verification is not complete yet.")
    name = pdf_service.download_filename(report.document_name)
    with repository.track_job(file_id, "report_generation"):
        try:
            pdf = pdf_service.build_pdf(report)
        except Exception:
            logger.exception("PDF generation failed for %s", file_id)
            raise err(500, "report_generation_failed", "The PDF report could not be generated. Please try again.")
        _record_report(file_id, name, pdf)
    return _pdf_response(pdf, name)


def _pdf_response(pdf: bytes, name: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------- stored files (kept in the database; served only through these authenticated routes) ----------

@app.get("/api/files/{file_id}")
def download_original(file_id: str, authorization: str | None = Header(default=None)):
    """The PDF that was uploaded, streamed from the database after the ownership check."""
    meta = auth.authorize(file_id, authorization)
    data = storage.load_pdf(file_id)
    if data is None:
        raise err(404, "file_not_found", "The original PDF is no longer stored.")
    return _pdf_response(data, meta["filename"] if meta["filename"].lower().endswith(".pdf") else meta["filename"] + ".pdf")


@app.get("/api/reports/{file_id}/saved")
def list_saved_reports(file_id: str, authorization: str | None = Header(default=None)):
    auth.authorize(file_id, authorization)
    return {"reports": repository.list_reports(file_id)}


@app.get("/api/reports/{file_id}/saved/{report_id}")
def download_saved_report(file_id: str, report_id: str, authorization: str | None = Header(default=None)):
    """Stream a previously generated report from the database (ownership is checked first)."""
    auth.authorize(file_id, authorization)
    if not storage.is_valid_id(report_id):
        raise err(404, "report_not_found", "That report was not found.")
    exists, key, name = repository.report_storage_key(file_id, report_id)  # a report of another document is "not found"
    if not exists or not key or not name:
        raise err(404, "report_not_found", "That report was not found.")
    data = filestore.get_store().read(key)
    if data is None:
        raise err(404, "report_not_found", "That report file is no longer stored.")
    return _pdf_response(data, name)
