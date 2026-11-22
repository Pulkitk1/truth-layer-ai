"""Document storage facade used by the services and API.

Everything is persistent and lives in Neon PostgreSQL: document metadata, claims, evidence, verdicts and summaries
(`repository`), and the PDF bytes themselves (`filestore`, table `file_objects`). Nothing is written to the server's
disk, so there are no temporary copies to clean up and nothing to lose on a restart.

Documents are identified by server-generated IDs only, never by user-supplied names."""
import logging
import re
import uuid

from . import filestore, repository
from .config import document_retention_days

logger = logging.getLogger("truthlayer")
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_file_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(file_id: str) -> bool:
    return bool(_ID_RE.fullmatch(file_id))


# ---------- documents ----------

def save_meta(file_id: str, filename: str, size: int, token_hash: str | None, data: bytes) -> None:
    """Create the document and store its PDF in one transaction (both are saved, or neither)."""
    repository.create_document(file_id, filename, size, None, token_hash, data)


def load_meta(file_id: str) -> dict | None:
    if not is_valid_id(file_id):
        return None
    doc = repository.get_document(file_id)
    return None if doc is None else {"filename": doc["filename"], "size": doc["size"]}


def load_pdf(file_id: str) -> bytes | None:
    """The original PDF's bytes, or None if there is none. Raises StorageError if it fails its checksum."""
    if not is_valid_id(file_id):
        return None
    return filestore.get_store().read(filestore.document_key(file_id))


# ---------- derived results ----------

_LOAD = {"claims": repository.load_claims, "search": repository.load_search, "verify": repository.load_verify, "summary": repository.load_summary}
_SAVE = {"claims": repository.save_claims, "search": repository.save_search, "verify": repository.save_verify, "summary": repository.save_summary}
_DELETE = {"search": repository.delete_search, "verify": repository.delete_verify, "summary": repository.delete_summary}


def _kind(file_id: str, kind: str) -> None:
    if not is_valid_id(file_id) or kind not in _LOAD:
        raise ValueError("invalid cache key")


def save_json(file_id: str, kind: str, data: dict) -> None:
    _kind(file_id, kind)
    _SAVE[kind](file_id, data)


def load_json(file_id: str, kind: str) -> dict | None:
    _kind(file_id, kind)
    return _LOAD[kind](file_id)


def delete_json(file_id: str, kind: str) -> None:
    _kind(file_id, kind)
    if kind in _DELETE:
        _DELETE[kind](file_id)


# ---------- deletion and retention ----------

def delete(file_id: str) -> bool:
    """Delete a document with everything that belongs to it (claims, evidence, verdicts, reports, jobs and every
    stored PDF) in one transaction. Returns False if it did not exist."""
    if not is_valid_id(file_id):
        return False
    return repository.delete_document(file_id)


def purge_expired() -> int:
    """Retention: delete documents older than DOCUMENT_RETENTION_DAYS (0 = keep forever), files included, skipping
    documents with an active job. Returns how many were deleted."""
    days = document_retention_days()
    if not days:
        return 0
    removed = 0
    for file_id in repository.expired_documents(days):
        if delete(file_id):
            removed += 1
    return removed
