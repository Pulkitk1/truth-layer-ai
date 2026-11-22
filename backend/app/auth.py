"""Per-document access tokens (anonymous ownership).

There are no user accounts. Uploading a PDF returns a random 256-bit access token ONCE; the database keeps only its
SHA-256 hash. Every later request about that document must send `Authorization: Bearer <token>`, so knowing a
document's id is no longer enough. The token is never put in a URL (URLs end up in logs and browser history) and is
never logged. SHA-256 is appropriate here because the token is a high-entropy random value, not a password, so it
cannot be guessed or brute-forced from its hash.

Status codes: 401 no/malformed token; 404 unknown document; 403 token does not belong to this document."""
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException

from . import repository, storage

_BEARER_RE = re.compile(r"^Bearer ([A-Za-z0-9_\-]{20,200})$")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _err(status: int, code: str, message: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def authorize(file_id: str, authorization: str | None) -> dict:
    """Return the document's metadata if `authorization` is the owner's token; raise 401/403/404 otherwise."""
    if not storage.is_valid_id(file_id):
        raise _err(404, "file_not_found", "Uploaded file not found or expired. Please upload again.")
    match = _BEARER_RE.match((authorization or "").strip())
    if not match:
        raise _err(401, "missing_token", "This document needs its access token. Upload the document again to get one.")
    exists, stored = repository.get_access(file_id)
    if not exists:
        raise _err(404, "file_not_found", "Uploaded file not found or expired. Please upload again.")
    # Documents created before tokens existed have no hash: nobody can prove ownership, so nobody gets in.
    if not stored or not hmac.compare_digest(hash_token(match.group(1)), stored):
        raise _err(403, "invalid_token", "You do not have access to this document.")
    meta = storage.load_meta(file_id)
    if meta is None:  # deleted between the two lookups
        raise _err(404, "file_not_found", "Uploaded file not found or expired. Please upload again.")
    return meta
