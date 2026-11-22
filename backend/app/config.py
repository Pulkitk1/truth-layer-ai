import os
import re
from pathlib import Path

from dotenv import load_dotenv

# override=True: the values in backend/.env always win over stale variables in the shell or system environment.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# Uploads are stored in the database (BYTEA), so the limit is capped at 20 MB however it is configured.
def clamp_upload_mb(raw: str) -> int:
    try:
        return max(1, min(int(raw), 20))
    except ValueError:
        return 20


MAX_UPLOAD_MB = clamp_upload_mb(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


# Groq settings are read lazily so they can be changed without re-importing.
def groq_api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def groq_model() -> str:
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL


def groq_timeout() -> float:
    return float(os.getenv("GROQ_TIMEOUT_SECONDS", "60"))


def chunk_chars() -> int:
    return int(os.getenv("CLAIM_CHUNK_CHARS", "6000"))


def max_chunks() -> int:
    return int(os.getenv("CLAIM_MAX_CHUNKS", "40"))


def database_url() -> str:
    """Connection string from DATABASE_URL (blank when no database is configured)."""
    return os.getenv("DATABASE_URL", "").strip()


# Tavily settings (web search / evidence collection), read lazily like Groq's.
def tavily_api_key() -> str:
    return os.getenv("TAVILY_API_KEY", "").strip()


def tavily_search_depth() -> str:
    d = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip().lower()
    return d if d in {"basic", "advanced"} else "basic"


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def tavily_max_results() -> int:
    """Sources returned per claim."""
    return _int_env("TAVILY_MAX_RESULTS", 5, 1, 10)


def tavily_fetch_results() -> int:
    """Results requested from Tavily per query (re-ranked locally, then trimmed)."""
    return max(tavily_max_results(), _int_env("TAVILY_FETCH_RESULTS", 8, 1, 20))


def tavily_timeout() -> float:
    try:
        return float(os.getenv("TAVILY_TIMEOUT_SECONDS", "20"))
    except ValueError:
        return 20.0


def max_search_claims() -> int:
    """Upper bound on claims searched per document (protects API credits)."""
    return _int_env("MAX_SEARCH_CLAIMS", 50, 1, 500)


# ---------- database (Neon PostgreSQL) ----------

def database_direct_url() -> str:
    """Non-pooled connection, used only by Alembic migrations. Falls back to DATABASE_URL."""
    return os.getenv("DATABASE_DIRECT_URL", "").strip()


def db_pool_size() -> int:
    return _int_env("DB_POOL_SIZE", 5, 1, 50)


def db_max_overflow() -> int:
    return _int_env("DB_MAX_OVERFLOW", 5, 0, 50)


def db_connect_timeout() -> int:
    """Seconds to wait for a connection (Neon may need a few seconds to wake an idle compute)."""
    return _int_env("DB_CONNECT_TIMEOUT_SECONDS", 15, 1, 120)


def document_retention_days() -> int:
    """Documents (with their stored files, reports and results) older than this are deleted. 0 keeps everything."""
    return _int_env("DOCUMENT_RETENTION_DAYS", 30, 0, 3650)


def retention_sweep_minutes() -> int:
    """How often the running backend looks for expired documents."""
    return _int_env("RETENTION_SWEEP_MINUTES", 60, 1, 1440)


def active_job_minutes() -> int:
    """A processing job still 'running' this recently protects its document from cleanup."""
    return _int_env("ACTIVE_JOB_MINUTES", 30, 1, 1440)


# ---------- environment, security and abuse protection ----------

def app_env() -> str:
    return "production" if os.getenv("APP_ENV", "").strip().lower() == "production" else "development"


def rate_limit_enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def rate_limits() -> dict[str, int]:
    """Requests allowed per client IP per minute, by kind of endpoint."""
    return {
        "upload": _int_env("RATE_LIMIT_UPLOAD_PER_MINUTE", 20, 1, 10000),
        "extract": _int_env("RATE_LIMIT_EXTRACT_PER_MINUTE", 10, 1, 10000),  # Groq: claim extraction, AI summary
        "search": _int_env("RATE_LIMIT_SEARCH_PER_MINUTE", 120, 1, 10000),  # Tavily
        "verify": _int_env("RATE_LIMIT_VERIFY_PER_MINUTE", 60, 1, 10000),  # Groq
        "default": _int_env("RATE_LIMIT_DEFAULT_PER_MINUTE", 300, 1, 100000),
    }


def trusted_proxy_count() -> int:
    """How many reverse proxies sit in front of the API (they append to X-Forwarded-For). 0 = none: use the socket IP."""
    return _int_env("TRUSTED_PROXY_COUNT", 0, 0, 10)


def client_ip_header() -> str:
    """Optional header that carries the real client IP, written (not appended) by a trusted proxy, for example
    CF-Connecting-IP on Render (Cloudflare overwrites it). Only used when TRUSTED_PROXY_COUNT is above 0."""
    name = os.getenv("CLIENT_IP_HEADER", "").strip()
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", name) else ""


def max_claim_extractions_per_hour() -> int:
    """Per document: how often Groq claim extraction may be (re)run in an hour."""
    return _int_env("MAX_CLAIM_EXTRACTIONS_PER_HOUR", 10, 1, 1000)


def max_pdf_pages() -> int:
    return _int_env("MAX_PDF_PAGES", 300, 1, 5000)
