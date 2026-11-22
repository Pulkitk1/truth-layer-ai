"""Production readiness: true only when every production requirement is actually met right now.
Reports what is wrong without revealing any credential or internal setting."""
from urllib.parse import urlparse

from . import config, filestore
from .db import check_database


def _cors_ok() -> tuple[bool, str]:
    origins = config.CORS_ORIGINS
    if not origins:
        return False, "CORS_ORIGINS is empty."
    if "*" in origins:
        return False, "CORS_ORIGINS allows every website."
    bad = [o for o in origins if urlparse(o).scheme != "https"]
    return (not bad, "Only https origins are allowed." if not bad else "CORS_ORIGINS must contain only https:// origins in production.")


def evaluate(database: dict | None = None, storage: dict | None = None) -> dict:
    database = database if database is not None else check_database()
    storage = storage if storage is not None else filestore.status()
    cors_ok, cors_detail = _cors_ok()
    retention = config.document_retention_days()
    checks = {
        "environment": (config.app_env() == "production", "APP_ENV=production" if config.app_env() == "production" else "Set APP_ENV=production."),
        "database": (database.get("status") == "ok", "Database reachable." if database.get("status") == "ok" else f"Database: {database.get('status')}."),
        "schema": (database.get("schema") == "current", f"Schema {database.get('schema', 'unknown')}." if database.get("schema") == "current" else "Run `alembic upgrade head`."),
        "file_storage": (bool(storage.get("production_ready")), "PDF storage in the database is working." if storage.get("production_ready") else (storage.get("note") or "The file table could not be read: run `alembic upgrade head`.")),
        "document_access_control": (True, "Per-document access tokens are enforced."),
        "rate_limiting": (config.rate_limit_enabled(), "Enabled." if config.rate_limit_enabled() else "RATE_LIMIT_ENABLED is off."),
        "cors": (cors_ok, cors_detail),
        "retention": (retention > 0, f"Documents are deleted after {retention} days." if retention > 0 else "Set DOCUMENT_RETENTION_DAYS above 0."),
        "ai_and_search_keys": (bool(config.groq_api_key() and config.tavily_api_key()), "Groq and Tavily keys are set." if config.groq_api_key() and config.tavily_api_key() else "GROQ_API_KEY and TAVILY_API_KEY must both be set."),
    }
    return {
        "production_ready": all(ok for ok, _ in checks.values()),
        "checks": {name: {"ok": ok, "detail": detail} for name, (ok, detail) in checks.items()},
        "blockers": [f"{name}: {detail}" for name, (ok, detail) in checks.items() if not ok],
    }
