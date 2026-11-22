"""Live checks against the real Neon database. Skipped by default (they need the network and DATABASE_URL).

    RUN_NEON_TESTS=1 python -m pytest tests/test_neon_live.py -v

They use only random document ids, spend no Groq/Tavily credits, and delete everything they create."""
import os
import uuid

import pytest
from sqlalchemy import inspect

import hashlib

from sqlalchemy import func, select

from app import config, filestore, repository, storage
from app.db.models import FileObject
from app.db import models, session
from tests.test_db import CLAIMS, search_cache, verify_cache

pytestmark = pytest.mark.skipif(os.environ.get("RUN_NEON_TESTS") != "1" or not config.database_url(), reason="set RUN_NEON_TESTS=1 (and DATABASE_URL) to run")


@pytest.fixture()
def neon():
    saved = session._engine, session._factory
    session._engine = session._factory = None
    engine = session.build_engine(config.database_url())
    session.set_engine(engine)
    created: list[str] = []
    yield created
    for fid in created:
        repository.delete_document(fid)
    engine.dispose()
    session._engine, session._factory = saved


def test_connection_health_and_tables(neon):
    health = session.check_database()
    assert health["status"] == "ok" and health["schema"] == "current", health
    tables = set(inspect(session.get_engine()).get_table_names())
    assert {"documents", "claims", "evidence", "verifications", "reports", "processing_jobs", "file_objects", "alembic_version"} <= tables


def test_every_record_type_persists_and_cascades(neon):
    fid = uuid.uuid4().hex
    neon.append(fid)
    pdf = b"%PDF-1.4 live test " + uuid.uuid4().bytes * 50
    repository.create_document(fid, "live-test.pdf", len(pdf), None, None, pdf)  # document + PDF in one transaction
    repository.mark_extracted(fid, 4, "success")
    repository.save_claims(fid, CLAIMS)
    repository.save_search(fid, search_cache(sources=[{"title": "T", "url": "https://x.example/a", "content": "c", "published_date": None,
                                                       "score": 0.5, "domain": "x.example", "source_type": "web", "claim_id": "claim_001"}]))
    repository.save_verify(fid, verify_cache())
    with repository.track_job(fid, "verification"):
        pass
    report_pdf = b"%PDF-1.4 live report " + uuid.uuid4().bytes * 20
    rid = repository.add_report(fid, "r.pdf", None, None, data=report_pdf)

    doc = repository.get_document(fid)
    assert (doc["filename"], doc["total_pages"], doc["extraction_status"]) == ("live-test.pdf", 4, "success")
    assert repository.load_claims(fid)["claims"] == CLAIMS["claims"]
    assert repository.load_search(fid)["results"]["claim_001"]["sources"][0]["url"] == "https://x.example/a"
    assert repository.load_verify(fid)["results"]["claim_001"]["result"]["verification_status"] == "VERIFIED"
    assert [j["status"] for j in repository.list_jobs(fid)] == ["completed"]
    assert [r["id"] for r in repository.list_reports(fid)] == [rid]

    store = filestore.get_store()
    assert storage.load_pdf(fid) == pdf  # BYTEA round trip, checksum verified
    assert store.read(filestore.report_key(rid)) == report_pdf
    assert store.describe(filestore.document_key(fid))["checksum"] == hashlib.sha256(pdf).hexdigest()
    assert filestore.status(force=True)["production_ready"] is True

    assert storage.delete(fid) is True
    with session.session_scope() as s:  # the files went with the document (ON DELETE CASCADE)
        assert s.scalar(select(func.count()).select_from(FileObject).where(FileObject.document_id == uuid.UUID(fid))) == 0
    assert repository.get_document(fid) is None and repository.load_claims(fid) is None
