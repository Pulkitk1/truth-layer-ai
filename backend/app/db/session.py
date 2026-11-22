"""Engine, sessions and health check. Credentials are read from the environment and never logged or returned."""
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .. import config

logger = logging.getLogger("truthlayer.db")
_lock = threading.Lock()
_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


class DbError(Exception):
    """A database problem, phrased for the end user. Never carries SQL, parameters or credentials."""

    def __init__(self, code: str, message: str, status: int = 503):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def normalize_url(url: str) -> str:
    """Neon gives `postgresql://`; SQLAlchemy needs to be told to use Psycopg 3 for it."""
    url = url.strip()
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def build_engine(url: str, *, pooled: bool = True) -> Engine:
    url = normalize_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_conn, _):  # cascade deletes need foreign keys switched on in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    kwargs: dict = {
        "pool_pre_ping": True,  # Neon closes idle connections; drop dead ones instead of failing a request
        "pool_recycle": 300,
        "connect_args": {
            "connect_timeout": config.db_connect_timeout(),
            # Neon's pooler (PgBouncer) shares server connections between clients, so do not cache
            # server-side prepared statements.
            "prepare_threshold": None,
        },
    }
    if pooled:
        kwargs.update(pool_size=config.db_pool_size(), max_overflow=config.db_max_overflow(), pool_timeout=config.db_connect_timeout())
    else:
        kwargs["poolclass"] = NullPool  # migrations: one short-lived connection
    return create_engine(url, **kwargs)


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            url = config.database_url()
            if not url:
                raise DbError(
                    "database_not_configured",
                    "The database is not configured. Set DATABASE_URL in backend/.env and restart the backend.",
                )
            _engine = build_engine(url)
            _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Install (or clear) the engine. Used by tests, and to release connections on shutdown."""
    global _engine, _factory
    with _lock:
        if _engine is not None and _engine is not engine:
            _engine.dispose()
        _engine = engine
        _factory = sessionmaker(engine, expire_on_commit=False) if engine is not None else None


def dispose_engine() -> None:
    set_engine(None)


def _to_db_error(exc: SQLAlchemyError) -> DbError:
    orig = getattr(exc, "orig", None)
    # Log the kind of failure only: statements and parameters can contain document text.
    logger.error("database error: %s (%s)", type(exc).__name__, type(orig).__name__ if orig else "-")
    if isinstance(exc, (OperationalError, PoolTimeoutError)) or (isinstance(exc, DBAPIError) and exc.connection_invalidated):
        return DbError("database_unavailable", "The database is temporarily unreachable. Please try again in a moment.")
    return DbError("database_error", "A database error occurred. Your request was not saved.", 500)


@contextmanager
def session_scope():
    """One unit of work: commits on success, rolls back on any error, always releases the connection."""
    get_engine()
    assert _factory is not None
    session = _factory()
    try:
        yield session
        session.commit()
    except DbError:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise _to_db_error(exc) from None
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


# ---------- health ----------

def _head_revision() -> str | None:
    root = Path(__file__).resolve().parents[2]
    ini = root / "alembic.ini"
    if not ini.exists():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_database() -> dict:
    """Is the database reachable and migrated? Returns a credential-free status dict (never raises)."""
    if not (config.database_url() or _engine is not None):
        return {"status": "not_configured", "message": "DATABASE_URL is not set."}
    started = time.perf_counter()
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            latency = round((time.perf_counter() - started) * 1000)
            try:
                current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except SQLAlchemyError:
                current = None
    except DbError as e:
        return {"status": "unavailable", "message": e.message}
    except SQLAlchemyError as exc:
        _to_db_error(exc)
        return {"status": "unavailable", "message": "The database could not be reached."}
    head = _head_revision()
    if current is None:
        schema = "not_migrated"
    elif head is None:
        schema = "unknown"
    else:
        schema = "current" if current == head else "outdated"
    return {"status": "ok" if schema in ("current", "unknown") else "needs_migration", "latency_ms": latency, "schema": schema, "revision": current}
