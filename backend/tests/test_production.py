"""GET /api/health: production_ready must be true only when every production requirement is really met."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config, filestore, main, readiness
from app.db import session
from app.db.session import DbError

SECRETS = ["groq-fake-test-secret-aaa", "tavily-fake-test-secret-bbb", "topsecret-db-password"]


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture()
def production(monkeypatch, _test_database):
    """Everything configured the way production should be (database via SQLite stamped as migrated)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GROQ_API_KEY", SECRETS[0])
    monkeypatch.setenv("TAVILY_API_KEY", SECRETS[1])
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "30")
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://truthlayer.example"])
    with _test_database.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        c.execute(text("DELETE FROM alembic_version"))
        c.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": session._head_revision()})
    filestore.set_store(None)
    yield
    with _test_database.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
    filestore.set_store(None)


def health(client):
    r = client.get("/api/health")
    return r.status_code, r.json()


def test_a_fully_configured_production_setup_is_ready_without_any_external_storage(client, production, monkeypatch):
    for k in ("STORAGE_BACKEND", "S3_BUCKET_NAME", "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)  # no R2, no S3
    code, body = health(client)
    assert code == 200 and body["status"] == "ok" and body["backend"] == "ok"
    assert body["production_ready"] is True and body["blockers"] == []
    assert all(c["ok"] for c in body["checks"].values()) and "object_storage" not in body["checks"]
    assert body["database"]["status"] == "ok" and body["schema"]["status"] == "current"
    st = body["storage"]
    assert st["backend"] == "database" and st["production_ready"] is True and st["reachable"] is True and st["private"] is True
    assert "stored_files" in st and "stored_megabytes" in st and body["environment"] == "production"


def test_the_development_setup_is_not_production_ready_yet_the_file_storage_check_passes(client):
    code, body = health(client)
    assert body["production_ready"] is False and body["blockers"]
    assert body["checks"]["file_storage"]["ok"] is True and not body["checks"]["environment"]["ok"]


@pytest.mark.parametrize(
    "name",
    ["environment", "database", "schema", "file_storage", "rate_limiting", "cors", "retention", "ai_and_search_keys"],
)
def test_each_missing_requirement_blocks_production_readiness(client, production, monkeypatch, name):
    saved = session._engine, session._factory
    if name == "environment":
        monkeypatch.setenv("APP_ENV", "development")
    elif name == "database":
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
        session.set_engine(session.build_engine("postgresql://u:p@127.0.0.1:1/x"))
    elif name == "schema":
        with session.get_engine().begin() as c:
            c.execute(text("UPDATE alembic_version SET version_num = '0000'"))
    elif name == "file_storage":
        monkeypatch.setattr(filestore.DatabaseFileStore, "usage", lambda self: (_ for _ in ()).throw(DbError("database_unavailable", "down")))
    elif name == "rate_limiting":
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    elif name == "cors":
        monkeypatch.setattr(config, "CORS_ORIGINS", ["http://localhost:3000"])
    elif name == "retention":
        monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "0")
    elif name == "ai_and_search_keys":
        monkeypatch.delenv("TAVILY_API_KEY")
    try:
        filestore.set_store(None)
        _, body = health(client)
    finally:
        session._engine, session._factory = saved
    assert body["production_ready"] is False
    assert not body["checks"][name]["ok"] and any(b.startswith(name) for b in body["blockers"])


def test_wildcard_cors_blocks_production(production, monkeypatch):
    monkeypatch.setattr(config, "CORS_ORIGINS", ["*"])
    assert readiness.evaluate()["checks"]["cors"]["ok"] is False


def test_an_unreadable_file_table_degrades_the_service(client, production, monkeypatch):
    monkeypatch.setattr(filestore.DatabaseFileStore, "usage", lambda self: (_ for _ in ()).throw(DbError("database_unavailable", "down")))
    filestore.set_store(None)
    code, body = health(client)
    assert code == 503 and body["status"] == "degraded" and body["storage"]["reachable"] is False and body["production_ready"] is False


def test_health_never_reveals_secrets(client, production, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://user:{SECRETS[2]}@host/db")
    r = client.get("/api/health")
    for secret in SECRETS:
        assert secret not in r.text
    assert "topsecret" not in str(session.check_database())


def test_health_is_degraded_with_503_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    saved = session._engine, session._factory
    session.set_engine(session.build_engine("postgresql://u:p@127.0.0.1:1/x"))
    try:
        filestore.set_store(None)
        r = client.get("/api/health")
    finally:
        session._engine, session._factory = saved
        filestore.set_store(None)
    assert r.status_code == 503 and r.json()["status"] == "degraded" and r.json()["production_ready"] is False
    assert r.json()["database"]["status"] == "unavailable" and r.json()["storage"]["reachable"] is False
