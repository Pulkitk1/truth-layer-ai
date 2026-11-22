"""Database layer: schema, relationships, persistence of every step, health check and failure handling.
Runs on throw-away SQLite (see conftest); the same code is exercised against Neon by test_neon_live.py."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import filestore, main, repository, storage
from app.db import models, session
from app.db.models import Claim, Document, Evidence, ProcessingJob, Report, Verification
from app.db.session import DbError
from tests.test_api import make_pdf


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return TestClient(main.app)


@pytest.fixture()
def swap_engine():
    """Temporarily replace the test engine (and put it back untouched afterwards)."""
    saved = session._engine, session._factory
    yield session.set_engine
    session._engine, session._factory = saved


def upload(client, name="doc.pdf") -> str:
    r = client.post("/api/upload", files={"file": (name, make_pdf(["Hello 1"]), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


CLAIMS = {
    "claims": [
        {"claim_id": "claim_001", "claim_text": "A grew 5 percent.", "normalized_claim": "A grew 5%", "category": "statistics",
         "value": "5", "unit": "percent", "time_period": "2024", "context": "ctx", "page_number": 1},
        {"claim_id": "claim_002", "claim_text": "B was founded in 1999.", "normalized_claim": None, "category": "company",
         "value": None, "unit": None, "time_period": None, "context": None, "page_number": 2},
    ],
    "status": "complete", "warnings": ["w"], "model": "m",
}


def source(cid="claim_001", url="https://www.rbi.org.in/a", content="text"):
    return {"title": "RBI", "url": url, "content": content, "published_date": "2024-05-01", "score": 0.9,
            "domain": "rbi.org.in", "source_type": "government", "claim_id": cid}


def search_cache(cid="claim_001", sources=None):
    srcs = [source(cid)] if sources is None else sources
    return {
        "queries": {cid: {"query": "q " + cid, "source": "ai"}},
        "results": {cid: {"claim_id": cid, "claim_text": "x", "page_number": 1, "search_status": "completed", "search_query": "q " + cid,
                          "query_source": "ai", "sources": srcs, "sources_found": len(srcs), "error": None}},
    }


def verify_cache(cid="claim_001", status="VERIFIED"):
    result = {"claim_id": cid, "original_claim": "x", "check_status": "completed", "verification_status": status, "claim_type": "factual",
              "explanation": "because", "corrected_claim": None, "confidence_score": 80, "evidence_summary": "sum",
              "supporting_sources": [], "contradicting_sources": [], "sources_considered": 1, "adjustments": [], "model": "m"}
    return {"results": {cid: {"fp": "f" * 24, "ev": "e" * 24, "result": result}}}


# ---------------------------------------------------------------- schema and helpers

def test_all_six_tables_exist_with_foreign_keys_and_indexes(_test_database):
    from sqlalchemy import inspect

    insp = inspect(_test_database)
    for t in ("documents", "claims", "evidence", "verifications", "reports", "processing_jobs"):
        assert t in insp.get_table_names()
        assert insp.get_pk_constraint(t)["constrained_columns"] == ["id"]
    assert {f["referred_table"] for f in insp.get_foreign_keys("claims")} == {"documents"}
    assert {f["referred_table"] for f in insp.get_foreign_keys("evidence")} == {"claims"}
    assert all(f["options"].get("ondelete") == "CASCADE" for t in ("claims", "evidence", "verifications", "reports", "processing_jobs") for f in insp.get_foreign_keys(t))
    assert any(i["column_names"] == ["document_id"] for i in insp.get_indexes("claims"))
    assert any(i["column_names"] == ["claim_id"] for i in insp.get_indexes("evidence"))


def test_normalize_url_selects_psycopg_3():
    assert session.normalize_url("postgresql://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert session.normalize_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert session.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


# ---------------------------------------------------------------- persistence of every step



def test_extraction_saves_page_count_and_status(client):
    fid = upload(client)
    assert client.post("/api/extract", json={"file_id": fid}).status_code == 200
    doc = repository.get_document(fid)
    assert doc["total_pages"] == 1 and doc["extraction_status"] == "success"


def test_corrupt_pdf_marks_extraction_failed(client):
    r = client.post("/api/upload", files={"file": ("bad.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")})
    fid = r.json()["file_id"]
    assert client.post("/api/extract", json={"file_id": fid}).status_code == 422
    assert repository.get_document(fid)["extraction_status"] == "failed"
    assert [(j["job_type"], j["status"]) for j in repository.list_jobs(fid)] == [("text_extraction", "failed")]
    assert "corrupted_pdf" in repository.list_jobs(fid)[0]["error_message"]


def test_claims_roundtrip(client):
    fid = upload(client)
    assert storage.load_json(fid, "claims") is None  # nothing extracted yet
    storage.save_json(fid, "claims", CLAIMS)
    got = storage.load_json(fid, "claims")
    assert got["claims"] == CLAIMS["claims"] and got["total_claims"] == 2
    assert (got["status"], got["warnings"], got["model"], got["file_id"]) == ("complete", ["w"], "m", fid)
    assert repository.get_document(fid)["processing_status"] == "claims_extracted"
    with session.session_scope() as s:
        assert [c.original_claim for c in s.scalars(select(Claim).where(Claim.document_id == uuid.UUID(fid)).order_by(Claim.position))] == ["A grew 5 percent.", "B was founded in 1999."]


def test_an_empty_extraction_is_still_remembered(client):
    fid = upload(client)
    storage.save_json(fid, "claims", {"claims": [], "status": "complete", "warnings": [], "model": "m"})
    assert storage.load_json(fid, "claims")["claims"] == []


def test_evidence_roundtrip_and_update(client):
    fid = upload(client)
    storage.save_json(fid, "claims", CLAIMS)
    assert storage.load_json(fid, "search") is None
    storage.save_json(fid, "search", search_cache(sources=[source(url="https://a.example/1"), source(url="https://b.example/2", content="other")]))
    got = storage.load_json(fid, "search")
    assert got["queries"]["claim_001"] == {"query": "q claim_001", "source": "ai"}
    r = got["results"]["claim_001"]
    assert r["search_status"] == "completed" and r["sources_found"] == 2
    assert [s["url"] for s in r["sources"]] == ["https://a.example/1", "https://b.example/2"]  # order kept
    assert r["sources"][0] == source(url="https://a.example/1")
    assert "claim_002" not in got["results"]
    # changed evidence replaces the old rows (no duplicates)
    storage.save_json(fid, "search", search_cache(sources=[source(url="https://c.example/3")]))
    assert [s["url"] for s in storage.load_json(fid, "search")["results"]["claim_001"]["sources"]] == ["https://c.example/3"]
    assert repository.get_document(fid)["processing_status"] == "evidence_collected"


def test_failed_search_state_is_kept_with_its_error(client):
    fid = upload(client)
    storage.save_json(fid, "claims", CLAIMS)
    cache = search_cache(sources=[])
    cache["results"]["claim_001"].update(search_status="no_results")
    storage.save_json(fid, "search", cache)
    assert storage.load_json(fid, "search")["results"]["claim_001"]["search_status"] == "no_results"


def test_verification_roundtrip_one_per_claim_and_replaced(client):
    fid = upload(client)
    storage.save_json(fid, "claims", CLAIMS)
    assert storage.load_json(fid, "verify") is None
    storage.save_json(fid, "verify", verify_cache(status="VERIFIED"))
    storage.save_json(fid, "verify", verify_cache(status="FALSE"))  # re-verification replaces, never duplicates
    got = storage.load_json(fid, "verify")["results"]["claim_001"]
    assert got["fp"] == "f" * 24 and got["ev"] == "e" * 24 and got["result"]["verification_status"] == "FALSE"
    with session.session_scope() as s:
        v = s.scalars(select(Verification).join(Claim).where(Claim.document_id == uuid.UUID(fid))).one()
        assert (v.verification_status, v.confidence_score, v.explanation, v.evidence_summary) == ("FALSE", 80, "because", "sum")
    assert repository.get_document(fid)["processing_status"] == "claims_extracted"  # claim_002 is not verified yet
    storage.save_json(fid, "verify", verify_cache("claim_002"))
    assert repository.get_document(fid)["processing_status"] == "verified"
    assert set(storage.load_json(fid, "verify")["results"]) == {"claim_001", "claim_002"}  # saves never erase other results


def test_summary_roundtrip(client):
    fid = upload(client)
    assert storage.load_json(fid, "summary") is None
    storage.save_json(fid, "summary", {"fp": "x", "narrative": "n", "model": "m"})
    assert storage.load_json(fid, "summary")["narrative"] == "n"
    storage.delete_json(fid, "summary")
    assert storage.load_json(fid, "summary") is None


def test_new_claim_extraction_discards_old_evidence_and_verdicts(client):
    fid = upload(client)
    storage.save_json(fid, "claims", CLAIMS)
    storage.save_json(fid, "search", search_cache())
    storage.save_json(fid, "verify", verify_cache())
    storage.save_json(fid, "claims", CLAIMS)
    assert storage.load_json(fid, "search") is None and storage.load_json(fid, "verify") is None


def test_delete_search_and_verify_only_clear_their_own_data(client):
    fid = upload(client)
    storage.save_json(fid, "claims", CLAIMS)
    storage.save_json(fid, "search", search_cache())
    storage.save_json(fid, "verify", verify_cache())
    storage.delete_json(fid, "verify")
    assert storage.load_json(fid, "verify") is None and storage.load_json(fid, "search") is not None
    storage.delete_json(fid, "search")
    assert storage.load_json(fid, "search") is None and storage.load_json(fid, "claims") is not None




def test_failed_pdf_download_is_recorded_as_a_failed_job(client, monkeypatch):
    from app import pdf_report
    from tests.pdf_fixture import make_big_doc

    monkeypatch.setenv("GROQ_API_KEY", "k")
    fid = make_big_doc(client, monkeypatch)
    monkeypatch.setattr(pdf_report, "build_pdf", lambda r: (_ for _ in ()).throw(RuntimeError("secret document text")))
    assert client.get(f"/api/report/{fid}").status_code == 500
    job = [j for j in repository.list_jobs(fid) if j["job_type"] == "report_generation"][-1]
    assert job["status"] == "failed" and "secret document text" not in job["error_message"]
    assert repository.list_reports(fid) == []


def test_jobs_are_tied_to_the_right_document_and_log_failures(client, monkeypatch):
    from app import llm
    from app.llm import LlmError

    a, b = upload(client, "a.pdf"), upload(client, "b.pdf")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm, "complete", lambda m: (_ for _ in ()).throw(LlmError("groq_rate_limited", "Slow down.", 429)))
    assert client.post("/api/claims/extract", json={"file_id": a}).status_code == 429
    assert [(j["job_type"], j["status"]) for j in repository.list_jobs(a)] == [("claim_extraction", "failed")]
    assert repository.list_jobs(a)[0]["error_message"] == "groq_rate_limited: Slow down."
    assert repository.list_jobs(b) == []


# ---------------------------------------------------------------- relationships and deletion

def test_relationships_and_cascade_delete_leave_other_documents_alone(client):
    a, b = upload(client, "a.pdf"), upload(client, "b.pdf")
    for fid in (a, b):
        storage.save_json(fid, "claims", CLAIMS)
        storage.save_json(fid, "search", search_cache(sources=[source(url="https://x.example/1"), source(url="https://x.example/2")]))
        storage.save_json(fid, "verify", verify_cache())
        repository.add_report(fid, "r.pdf", None, 1)
    with session.session_scope() as s:
        doc = s.get(Document, uuid.UUID(a))
        assert len(doc.claims) == 2 and len(doc.claims[0].evidence) == 2 and doc.claims[0].verification is not None
        assert len(doc.reports) == 1
    assert storage.delete(a) is True
    with session.session_scope() as s:
        assert s.get(Document, uuid.UUID(a)) is None
        assert s.scalar(select(func.count()).select_from(Claim).where(Claim.document_id == uuid.UUID(a))) == 0
        assert s.scalar(select(func.count()).select_from(Report).where(Report.document_id == uuid.UUID(a))) == 0
        assert s.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.document_id == uuid.UUID(a))) == 0
    assert storage.load_json(b, "verify") is not None and len(storage.load_json(b, "search")["results"]["claim_001"]["sources"]) == 2
    assert repository.list_reports(b)


def test_database_rejects_invalid_values():
    with pytest.raises(DbError) as e:
        with session.session_scope() as s:
            s.add(Document(filename="x.pdf", file_size=1, processing_status="bogus"))
    assert e.value.code == "database_error" and "bogus" not in e.value.message
    with pytest.raises(DbError):
        with session.session_scope() as s:
            s.add(Document(filename="x.pdf", file_size=-5))


def test_a_failed_unit_of_work_is_rolled_back(client):
    fid = upload(client)
    with pytest.raises(DbError):
        with session.session_scope() as s:
            s.get(Document, uuid.UUID(fid)).filename = "renamed.pdf"
            s.flush()
            s.add(Document(id=uuid.UUID(fid), filename="dup", file_size=1))  # primary key clash
    assert repository.get_document(fid)["filename"] == "doc.pdf"















# ---------------------------------------------------------------- health check and failure handling

def test_health_reports_database_and_schema(client, _test_database):
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["database"]["schema"] == "not_migrated"  # tests build tables without Alembic
    with _test_database.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        c.execute(text("DELETE FROM alembic_version"))
        c.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": session._head_revision()})
    try:
        body = client.get("/api/health").json()
        assert body["status"] == "ok" and body["backend"] == "ok"
        assert body["database"]["status"] == "ok" and body["database"]["schema"] == "current" and "latency_ms" in body["database"]
        assert body["storage"]["backend"] == "database" and body["storage"]["production_ready"] is True
        assert "max_upload_mb" in body
    finally:
        with _test_database.begin() as c:
            c.execute(text("DROP TABLE alembic_version"))


def test_unreachable_database_gives_a_clean_503_without_leaking_credentials(client, swap_engine, monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    swap_engine(session.build_engine("postgresql://someuser:s3cretpass@127.0.0.1:1/nodb"))
    h = client.get("/api/health")
    assert h.status_code == 503 and h.json()["status"] == "degraded" and h.json()["database"]["status"] == "unavailable"
    assert "s3cretpass" not in h.text and "someuser" not in h.text
    r = client.post("/api/upload", files={"file": ("d.pdf", make_pdf(["x 1"]), "application/pdf")})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "database_unavailable"
    assert "s3cretpass" not in r.text
    assert r.json()["detail"]["message"].startswith("The database is temporarily unreachable")


def test_a_failed_upload_leaves_nothing_behind(client, swap_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    swap_engine(session.build_engine("postgresql://u:p@127.0.0.1:1/nodb"))
    client.post("/api/upload", files={"file": ("d.pdf", make_pdf(["x 1"]), "application/pdf")})
    assert list(tmp_path.glob("*.pdf")) == []


def test_missing_database_url_is_reported_clearly(client, swap_engine, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    swap_engine(None)
    h = client.get("/api/health")
    assert h.status_code == 503 and h.json()["database"]["status"] == "not_configured"
    r = client.post("/api/upload", files={"file": ("d.pdf", make_pdf(["x 1"]), "application/pdf")})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "database_not_configured"


def test_the_api_still_starts_when_the_database_is_down(swap_engine, monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    swap_engine(session.build_engine("postgresql://u:p@127.0.0.1:1/nodb"))
    monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "1")
    with TestClient(main.app) as c:  # runs the startup hook, which must not crash
        assert c.get("/api/health").status_code == 503

