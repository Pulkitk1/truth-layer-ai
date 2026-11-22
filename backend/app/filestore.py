"""File storage in Neon PostgreSQL: uploaded PDFs and generated reports are kept in the `file_objects` table (BYTEA).

There is no external object storage. This keeps the project simple (one service, one backup, one set of credentials) and
is fine for an assignment-sized app, but it has limits: see "Database file storage limits" in the README.

Rules:
  * Keys are server-generated (`documents/<file_id>.pdf`, `reports/<report_id>.pdf`) and parsed strictly, so a key can
    never reach anything but its own row.
  * `put` runs inside the CALLER's transaction. The document row and its PDF are therefore saved together or not at
    all, and a generated report and its metadata likewise.
  * Every file carries a SHA-256 checksum, computed before saving and verified every time it is read. The stored size is
    also read back inside the transaction before it commits.
  * An identical file is never stored twice for the same document.
  * Nothing is public: files leave the database only through the authenticated API. The bytes are never part of a JSON
    response and never logged.
  * Deleting a document deletes its files in the same transaction (ON DELETE CASCADE): no orphans, no cleanup job."""
import hashlib
import logging
import re
import time
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import session as dbsession
from .db.models import FileObject
from .db.session import DbError, session_scope

logger = logging.getLogger("truthlayer.files")
_KEY_RE = re.compile(r"^(documents|reports)/([0-9a-f]{32})\.pdf$")
ORIGINAL, REPORT = "original_pdf", "generated_report"
MIME = "application/pdf"


class StorageError(Exception):
    """A stored file could not be saved or failed its integrity check. Messages are safe to show users."""

    def __init__(self, message: str = "File storage failed. Please try again.", code: str = "storage_error", status: int = 502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def document_key(file_id: str) -> str:
    return f"documents/{file_id}.pdf"


def report_key(report_id: str) -> str:
    return f"reports/{report_id}.pdf"


def parse_key(key: str) -> tuple[str, uuid.UUID]:
    """('original_pdf' | 'generated_report', id). Raises ValueError for anything that is not a valid key."""
    m = _KEY_RE.fullmatch(key)
    if not m:
        raise ValueError("invalid storage key")
    return (ORIGINAL if m.group(1) == "documents" else REPORT), uuid.UUID(hex=m.group(2))


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _where(key: str):
    kind, ident = parse_key(key)
    if kind == ORIGINAL:
        return (FileObject.document_id == ident) & (FileObject.file_type == ORIGINAL)
    return (FileObject.id == ident) & (FileObject.file_type == REPORT)


class DatabaseFileStore:
    def put(self, session: Session, key: str, document_id: uuid.UUID, filename: str, data: bytes) -> tuple[uuid.UUID, bool]:
        """Add a file to the caller's transaction. Returns (file id, created); created is False when this document
        already holds an identical file, in which case nothing new is stored."""
        kind, ident = parse_key(key)
        if not data:
            raise StorageError("The file is empty.", "storage_error", 400)
        digest = checksum(data)
        existing = session.scalar(
            select(FileObject.id).where(FileObject.document_id == document_id, FileObject.file_type == kind, FileObject.checksum == digest)
        )
        if existing is not None:
            return existing, False
        obj = FileObject(
            id=ident if kind == REPORT else uuid.uuid4(),
            document_id=document_id,
            file_type=kind,
            filename=filename[:255],
            mime_type=MIME,
            file_size=len(data),
            file_content=data,
            checksum=digest,
        )
        session.add(obj)
        session.flush()
        stored = session.scalar(select(func.length(FileObject.file_content)).where(FileObject.id == obj.id))
        if stored != len(data):  # read the size back before committing: a mismatch aborts (rolls back) the whole save
            logger.error("stored file size mismatch")
            raise StorageError("The file could not be stored completely. Please try again.")
        return obj.id, True

    def read(self, key: str) -> bytes | None:
        """The file's bytes, or None if there is no such file. Raises StorageError if the bytes fail their checksum."""
        with session_scope() as s:
            row = s.execute(select(FileObject.file_content, FileObject.checksum, FileObject.file_size).where(_where(key))).first()
        if row is None:
            return None
        data = bytes(row.file_content)
        if len(data) != row.file_size or checksum(data) != row.checksum:
            logger.error("a stored file failed its integrity check")
            raise StorageError("The stored file failed its integrity check, so it was not returned.", "storage_corrupt", 500)
        return data

    def describe(self, key: str) -> dict | None:
        """Name, size and checksum without loading the bytes."""
        with session_scope() as s:
            row = s.execute(select(FileObject.filename, FileObject.file_size, FileObject.checksum, FileObject.created_at).where(_where(key))).first()
        return None if row is None else {"filename": row.filename, "size": row.file_size, "checksum": row.checksum, "created_at": row.created_at}

    def exists(self, key: str) -> bool:
        return self.describe(key) is not None

    def delete(self, key: str) -> None:
        with session_scope() as s:
            s.execute(delete(FileObject).where(_where(key)))

    def usage(self) -> dict:
        with session_scope() as s:
            count, total = s.execute(select(func.count(FileObject.id), func.coalesce(func.sum(FileObject.file_size), 0))).one()
        return {"stored_files": int(count), "stored_megabytes": round(int(total) / 1_048_576, 2)}

    def check(self) -> dict:
        """Can the file table be read? (The database connection itself is checked separately.)"""
        try:
            return {"reachable": True, "private": True, **self.usage()}
        except DbError:
            return {"reachable": False, "private": True}

    def info(self) -> dict:
        return {"backend": "database"}


# ---------------------------------------------------------------- selection and cached status

_store: DatabaseFileStore | None = None
_status: tuple[float, int, dict] | None = None
_STATUS_TTL = 60.0


def get_store() -> DatabaseFileStore:
    global _store
    if _store is None:
        _store = DatabaseFileStore()
    return _store


def set_store(store: DatabaseFileStore | None) -> None:
    global _store, _status
    _store, _status = store, None


def status(force: bool = False) -> dict:
    """Credential-free storage status for /api/health (cached for a minute, and per database connection)."""
    global _status
    now, engine_id = time.monotonic(), id(dbsession._engine)
    if not force and _status is not None and _status[1] == engine_id and now - _status[0] < _STATUS_TTL:
        return _status[2]
    probe = get_store().check()
    result = {
        **get_store().info(),
        **probe,
        "production_ready": bool(probe["reachable"]),
        "note": "Files are stored in the database (BYTEA); see the README for the size and capacity limits."
        if probe["reachable"]
        else "The file table could not be read.",
    }
    _status = (now, engine_id, result)
    return result
