"""Alembic environment. The URL comes from backend/.env (DATABASE_DIRECT_URL, else DATABASE_URL); it is never
stored in alembic.ini and never printed."""
from logging.config import fileConfig

from alembic import context

from app import config
from app.db.models import Base
from app.db.session import build_engine, normalize_url

alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = config.database_direct_url() or config.database_url()
    if not url:
        raise SystemExit("Set DATABASE_URL (and optionally DATABASE_DIRECT_URL) in backend/.env before running migrations.")
    return normalize_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(_url(), pooled=False)  # one short-lived connection
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
