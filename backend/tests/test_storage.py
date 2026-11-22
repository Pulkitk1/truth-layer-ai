"""PDF storage in Neon PostgreSQL (table file_objects): uploads, retrieval, integrity, reports, deletion, retention.
Runs on throw-away SQLite; test_neon_live.py repeats the key flows against the real database."""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, update

from app import config, filestore, main, repository, storage
from app import pdf_report as pdf_service
from app.db import session
from app.db.models import Document, FileObject, ProcessingJob
from app.db.session import DbError
from app.filestore import StorageError
from tests.test_api import make_pdf


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return TestClient(main.app, raise_server_exceptions=False)


def upload(client, pages=("Revenue grew 12 percent in 2023.",), name="d.pdf"):
    data = make_pdf(list(pages))
    r = client.post("/api/upload", files={"file": (name, data, "application/pdf")})
    return r, data


def new_doc(client, **kw):
    r, data = upload(client, **kw)
    assert r.status_code == 200, r.text
    return r.json()["file_id"], data


def count(model, *where) -> int:
    with session.session_scope() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where)) or 0


def verified_document(client, monkeypatch):
    from tests.pdf_fixture import make_big_doc

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "m")
    return make_big_doc(client, monkeypatch)


# ---------------------------------------------------------------- uploading into the database

def test_an_uploaded_pdf_is_stored_in_the_database_with_its_checksum(client):
    fid, data = new_doc(client)
    info = filestore.get_store().describe(filestore.document_key(fid))
    assert info["size"] == len(data) and info["checksum"] == hashlib.sha256(data).hexdigest()
    with session.session_scope() as s:
        row = s.scalars(select(FileObject).where(FileObject.document_id == uuid.UUID(fid))).one()
        assert (row.file_type, row.mime_type, row.file_size, row.filename) == ("original_pdf", "application/pdf", len(data), "d.pdf")
    assert repository.get_document(fid)["storage_key"] == f"documents/{fid}.pdf"


def test_the_original_pdf_is_retrieved_byte_for_byte_and_only_through_the_api(client):
    fid, data = new_doc(client, name="Annual Report.pdf")
    r = client.get(f"/api/files/{fid}")
    assert r.status_code == 200 and r.content == data and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"] and "Annual" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert storage.load_pdf(fid) == data


def test_text_is_extracted_from_the_pdf_stored_in_the_database_without_touching_the_disk(client, tmp_path, monkeypatch):
    import builtins

    fid, _ = new_doc(client, pages=("Hello stored world.", "Second page here."))
    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: opened.append(str(f)) or real_open(f, *a, **k))
    r = client.post("/api/extract", json={"file_id": fid})
    monkeypatch.undo()
    assert r.status_code == 200 and r.json()["total_pages"] == 2 and "Hello stored world." in r.json()["extracted_text"]
    assert not any(str(tmp_path) in o for o in opened) and list(tmp_path.iterdir()) == []


def test_json_responses_never_contain_pdf_bytes(client):
    fid, data = new_doc(client)
    for url in (f"/api/reports/{fid}", f"/api/reports/{fid}/saved"):
        r = client.get(url)
        assert "%PDF" not in r.text and "file_content" not in r.text
    up, _ = upload(client)
    assert "%PDF" not in up.text and set(up.json()) == {"file_id", "filename", "file_size", "upload_status", "access_token"}
    assert "%PDF" not in client.post("/api/extract", json={"file_id": fid}).text


def test_pdf_contents_never_reach_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    fid, _ = new_doc(client, pages=("SECRET-MARKER-XYZ is confidential.",))
    client.post("/api/extract", json={"file_id": fid})
    client.get(f"/api/files/{fid}")
    client.delete(f"/api/files/{fid}")
    assert "SECRET-MARKER-XYZ" not in caplog.text and "%PDF" not in caplog.text


def test_listing_files_does_not_load_their_bytes(client):
    fid, _ = new_doc(client)
    with session.session_scope() as s:
        obj = s.scalars(select(FileObject).where(FileObject.document_id == uuid.UUID(fid))).one()
        assert "file_content" in inspect(obj).unloaded  # deferred: only fetched when read() asks for it


# ---------------------------------------------------------------- size and type limits, atomic saves

def test_the_upload_limit_is_enforced_before_anything_is_saved(client, monkeypatch):
    assert config.MAX_UPLOAD_BYTES <= 20 * 1024 * 1024
    docs, files = count(Document), count(FileObject)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1000)
    r = client.post("/api/upload", files={"file": ("big.pdf", b"%PDF-" + b"0" * 5000, "application/pdf")})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "file_too_large"
    assert (count(Document), count(FileObject)) == (docs, files)


@pytest.mark.parametrize("data,code", [(b"", "empty_file"), (b"<html>nope</html>", "invalid_pdf")])
def test_invalid_uploads_store_nothing(client, data, code):
    docs, files = count(Document), count(FileObject)
    r = client.post("/api/upload", files={"file": ("x.pdf", data, "application/pdf")})
    assert r.json()["detail"]["code"] == code
    assert (count(Document), count(FileObject)) == (docs, files)


def test_the_configured_limit_can_never_exceed_20_mb():
    assert [config.clamp_upload_mb(v) for v in ("500", "20", "5", "0", "-3", "abc", "")] == [20, 20, 5, 1, 1, 20, 20]


def test_the_document_and_its_pdf_are_saved_together_or_not_at_all(client, monkeypatch):
    docs, files = count(Document), count(FileObject)

    def fail(self, *a, **k):
        raise StorageError("The file could not be stored completely. Please try again.")

    monkeypatch.setattr(filestore.DatabaseFileStore, "put", fail)
    r, _ = upload(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "storage_error"
    assert (count(Document), count(FileObject)) == (docs, files)  # no document row without its file


def test_a_size_mismatch_read_back_inside_the_transaction_rolls_everything_back(client, monkeypatch):
    docs, files = count(Document), count(FileObject)

    class WrongLength:
        def __getattr__(self, name):
            return getattr(sa.func, name)

        @staticmethod
        def length(col):
            return sa.literal(-1)

    monkeypatch.setattr(filestore, "func", WrongLength())
    r, _ = upload(client)
    assert r.status_code == 502 and "stored completely" in r.json()["detail"]["message"]
    assert (count(Document), count(FileObject)) == (docs, files)


def test_a_database_outage_during_upload_is_a_clean_503(client, monkeypatch):
    saved = session._engine, session._factory
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    session.set_engine(session.build_engine("postgresql://u:topsecretpw@127.0.0.1:1/x"))
    try:
        r, _ = upload(client)
    finally:
        session._engine, session._factory = saved
    assert r.status_code == 503 and r.json()["detail"]["code"] == "database_unavailable" and "topsecretpw" not in r.text


# ---------------------------------------------------------------- integrity

def test_a_file_that_fails_its_checksum_is_never_returned(client):
    fid, _ = new_doc(client)
    with session.session_scope() as s:
        s.execute(update(FileObject).where(FileObject.document_id == uuid.UUID(fid)).values(file_content=b"%PDF-tampered"))
    with pytest.raises(StorageError) as e:
        storage.load_pdf(fid)
    assert e.value.code == "storage_corrupt"
    for r in (client.post("/api/extract", json={"file_id": fid}), client.get(f"/api/files/{fid}")):
        assert r.status_code == 500 and r.json()["detail"]["code"] == "storage_corrupt" and "tampered" not in r.text


def test_identical_files_are_stored_once_per_document(client):
    fid, data = new_doc(client)
    store = filestore.get_store()
    with session.session_scope() as s:
        doc = s.get(Document, uuid.UUID(fid))
        again, created = store.put(s, filestore.document_key(fid), doc.id, "d.pdf", data)
    assert created is False and count(FileObject, FileObject.document_id == uuid.UUID(fid)) == 1


def test_the_database_enforces_the_file_rules(client):
    fid, data = new_doc(client)
    doc = uuid.UUID(fid)

    def insert(**over):
        row = dict(document_id=doc, file_type="generated_report", filename="r.pdf", mime_type="application/pdf", file_size=3, file_content=b"abc", checksum="c" * 64)
        row.update(over)
        with session.session_scope() as s:
            s.add(FileObject(**row))

    insert()  # a valid report
    for bad in (
        dict(file_type="original_pdf", checksum="d" * 64),  # a second original PDF for the same document
        dict(checksum="c" * 64),  # the same report content twice
        dict(file_type="spreadsheet", checksum="e" * 64),
        dict(mime_type="text/html", checksum="f" * 64),
        dict(file_size=0, checksum="1" * 64),
        dict(document_id=uuid.uuid4(), checksum="2" * 64),  # no such document
    ):
        with pytest.raises(DbError):
            insert(**bad)


def test_keys_are_parsed_strictly():
    assert filestore.parse_key(filestore.document_key("a" * 32))[0] == "original_pdf"
    assert filestore.parse_key(filestore.report_key("b" * 32))[0] == "generated_report"
    for bad in ("../x.pdf", "documents/x.pdf", "documents/" + "a" * 32 + ".exe", "other/" + "a" * 32 + ".pdf", "documents/../" + "a" * 32 + ".pdf", "/" + "a" * 32):
        with pytest.raises(ValueError):
            filestore.parse_key(bad)
    assert filestore.get_store().read(filestore.document_key("0" * 32)) is None


# ---------------------------------------------------------------- generated reports

def test_generated_reports_are_saved_in_the_database_and_downloaded_from_it(client, monkeypatch):
    fid = verified_document(client, monkeypatch)
    pdf = client.get(f"/api/report/{fid}")
    assert pdf.status_code == 200
    listed = client.get(f"/api/reports/{fid}/saved").json()["reports"]
    assert len(listed) == 1 and listed[0]["has_file"] is True and listed[0]["file_size"] > 1000
    got = client.get(f"/api/reports/{fid}/saved/{listed[0]['id']}")
    assert got.status_code == 200 and got.content.startswith(b"%PDF-") and len(got.content) == listed[0]["file_size"]
    assert got.headers["content-type"] == "application/pdf" and "attachment" in got.headers["content-disposition"]
    with session.session_scope() as s:
        row = s.scalars(select(FileObject).where(FileObject.document_id == uuid.UUID(fid), FileObject.file_type == "generated_report")).one()
        assert row.id.hex == listed[0]["id"] and row.checksum == hashlib.sha256(got.content).hexdigest()


def test_one_document_can_have_many_reports_but_identical_ones_are_not_duplicated(client, monkeypatch):
    fid = verified_document(client, monkeypatch)
    n = iter(range(100))
    monkeypatch.setattr(pdf_service, "build_pdf", lambda report: b"%PDF-1.4 distinct " + str(next(n)).encode())
    for _ in range(3):
        assert client.get(f"/api/report/{fid}").status_code == 200
    assert len(client.get(f"/api/reports/{fid}/saved").json()["reports"]) == 3
    assert count(FileObject, FileObject.document_id == uuid.UUID(fid), FileObject.file_type == "generated_report") == 3
    monkeypatch.setattr(pdf_service, "build_pdf", lambda report: b"%PDF-1.4 same every time")
    for _ in range(3):
        assert client.get(f"/api/report/{fid}").content == b"%PDF-1.4 same every time"  # the user still gets the PDF
    assert len(client.get(f"/api/reports/{fid}/saved").json()["reports"]) == 4  # ...but only one new copy was stored


def test_a_report_still_downloads_when_its_copy_cannot_be_saved(client, monkeypatch):
    fid = verified_document(client, monkeypatch)
    monkeypatch.setattr(filestore.DatabaseFileStore, "put", lambda *a, **k: (_ for _ in ()).throw(StorageError()))
    r = client.get(f"/api/report/{fid}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    assert client.get(f"/api/reports/{fid}/saved").json() == {"reports": []}  # metadata and file are saved together: neither exists


def test_a_report_of_another_document_is_not_found(client, monkeypatch):
    fid = verified_document(client, monkeypatch)
    client.get(f"/api/report/{fid}")
    rid = client.get(f"/api/reports/{fid}/saved").json()["reports"][0]["id"]
    other, _ = new_doc(client)
    assert client.get(f"/api/reports/{other}/saved/{rid}").status_code == 404
    assert client.get(f"/api/reports/{fid}/saved/not-an-id").status_code == 404
    assert client.get(f"/api/reports/{fid}/saved/{'0' * 32}").status_code == 404


# ---------------------------------------------------------------- missing files

def test_documents_without_a_stored_file_report_it_clearly(client):
    from app import auth

    token = "L" * 43  # a document row with no file behind it (e.g. created before files moved into the database)
    fid = storage.new_file_id()
    repository.create_document(fid, "legacy.pdf", 10, None, auth.hash_token(token))
    anon = TestClient(main.app, raise_server_exceptions=False)
    anon.auto_auth = False
    h = {"Authorization": f"Bearer {token}"}
    for r in (anon.post("/api/extract", json={"file_id": fid}, headers=h), anon.get(f"/api/files/{fid}", headers=h)):
        assert r.status_code == 404 and r.json()["detail"]["code"] == "file_not_found"


def test_a_report_row_whose_file_is_missing_is_not_found(client):
    fid, _ = new_doc(client)
    rid = repository.add_report(fid, "r.pdf", "reports/" + "9" * 32 + ".pdf", 10)  # metadata only, no file
    assert client.get(f"/api/reports/{fid}/saved/{rid}").status_code == 404


# ---------------------------------------------------------------- deletion and retention

def test_deleting_a_document_deletes_its_files_in_the_same_step(client, monkeypatch):
    fid = verified_document(client, monkeypatch)
    client.get(f"/api/report/{fid}")
    other, other_data = new_doc(client)
    assert count(FileObject, FileObject.document_id == uuid.UUID(fid)) == 2
    assert client.delete(f"/api/files/{fid}").status_code == 200
    assert count(FileObject, FileObject.document_id == uuid.UUID(fid)) == 0
    assert repository.get_document(fid) is None and storage.load_pdf(fid) is None
    assert storage.load_pdf(other) == other_data  # another document's file is untouched


def test_expired_documents_are_deleted_with_their_files(client, monkeypatch):
    monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "7")
    old, _ = new_doc(client)
    fresh, fresh_data = new_doc(client)
    with session.session_scope() as s:
        s.get(Document, uuid.UUID(old)).created_at = datetime.now(timezone.utc) - timedelta(days=8)
    assert storage.purge_expired() == 1
    assert repository.get_document(old) is None and count(FileObject, FileObject.document_id == uuid.UUID(old)) == 0
    assert storage.load_pdf(fresh) == fresh_data


def test_retention_skips_documents_with_an_active_job_and_can_be_switched_off(client, monkeypatch):
    fid, _ = new_doc(client)
    with session.session_scope() as s:
        s.get(Document, uuid.UUID(fid)).created_at = datetime.now(timezone.utc) - timedelta(days=40)
    monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "0")
    assert storage.purge_expired() == 0 and repository.get_document(fid) is not None
    monkeypatch.setenv("DOCUMENT_RETENTION_DAYS", "1")
    with repository.track_job(fid, "verification"):
        assert storage.purge_expired() == 0 and storage.load_pdf(fid) is not None
        with session.session_scope() as s:  # a job stuck "running" for hours (e.g. after a restart) no longer protects it
            job = s.scalars(select(ProcessingJob).where(ProcessingJob.status == "running", ProcessingJob.document_id == uuid.UUID(fid))).one()
            job.updated_at = datetime.now(timezone.utc) - timedelta(hours=3)
        assert storage.purge_expired() == 1
    assert repository.get_document(fid) is None


def test_the_default_retention_period_is_30_days(monkeypatch):
    monkeypatch.delenv("DOCUMENT_RETENTION_DAYS", raising=False)
    assert config.document_retention_days() == 30


# ---------------------------------------------------------------- persistence across a restart

def test_files_and_results_survive_a_backend_restart(client, _test_database, monkeypatch):
    fid = verified_document(client, monkeypatch)
    pdf = client.get(f"/api/report/{fid}")
    original = storage.load_pdf(fid)
    assert original and pdf.status_code == 200
    token = __import__("tests.conftest", fromlist=["_TOKENS"])._TOKENS[fid]

    saved = session._engine, session._factory
    url = _test_database.url.render_as_string(hide_password=False)
    session._engine = session._factory = None  # the old process is gone: no engine, no cached store...
    filestore.set_store(None)
    session.set_engine(session.build_engine(url))  # ...a new one connects to the same database
    try:
        fresh = TestClient(main.app, raise_server_exceptions=False)
        fresh.auto_auth = False
        h = {"Authorization": f"Bearer {token}"}
        assert fresh.get(f"/api/files/{fid}", headers=h).content == original
        assert fresh.get(f"/api/reports/{fid}", headers=h).json()["counts"]["total"] == 12
        saved_reports = fresh.get(f"/api/reports/{fid}/saved", headers=h).json()["reports"]
        assert len(saved_reports) == 1
        assert fresh.get(f"/api/reports/{fid}/saved/{saved_reports[0]['id']}", headers=h).content.startswith(b"%PDF-")
        assert fresh.post("/api/extract", json={"file_id": fid}, headers=h).status_code == 200
    finally:
        session.set_engine(None)
        session._engine, session._factory = saved


# ---------------------------------------------------------------- status

def test_the_storage_status_reports_usage_without_secrets(client):
    new_doc(client)
    st = filestore.status(force=True)
    assert st["backend"] == "database" and st["reachable"] is True and st["production_ready"] is True and st["private"] is True
    assert st["stored_files"] >= 1 and st["stored_megabytes"] >= 0 and "note" in st
    assert "postgres" not in str(st).lower()


def test_the_storage_status_notices_an_unreadable_file_table(monkeypatch):
    monkeypatch.setattr(filestore.DatabaseFileStore, "usage", lambda self: (_ for _ in ()).throw(DbError("database_unavailable", "down")))
    st = filestore.status(force=True)
    assert st["reachable"] is False and st["production_ready"] is False
    filestore.set_store(None)


# ---------------------------------------------------------------- moving old local files into the database

def _load_migrator():
    import importlib.util
    from pathlib import Path as P

    spec = importlib.util.spec_from_file_location("migrate_local_files", P(__file__).resolve().parents[1] / "scripts" / "migrate_local_files.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_leftover_local_files_are_copied_verified_and_kept_unless_asked(client, tmp_path):
    mig = _load_migrator()
    fid, _ = new_doc(client)
    with session.session_scope() as s:  # simulate a document from the local-file era: its database copy does not exist yet
        s.execute(sa.delete(FileObject).where(FileObject.document_id == uuid.UUID(fid)))
    old = b"%PDF-1.4 legacy local file"
    root = tmp_path / "old-storage"
    (root / "documents").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "documents" / f"{fid}.pdf").write_bytes(old)
    stray = root / "documents" / f"{'a' * 32}.pdf"
    stray.write_bytes(b"%PDF- belongs to nobody")
    rid = "c" * 32  # legacy rows hold a key built from their own id
    repository.add_report(fid, "r.pdf", filestore.report_key(rid), 5, report_id=rid)
    (root / "reports" / f"{rid}.pdf").write_bytes(b"%PDF-1.4 legacy report")

    first = mig.migrate(root)
    assert first["copied"] == 2 and first["verified"] == 2 and first["skipped_no_record"] == 1 and first["failed"] == 0 and first["deleted_local"] == 0
    assert storage.load_pdf(fid) == old and (root / "documents" / f"{fid}.pdf").exists()  # local files are preserved
    assert client.get(f"/api/reports/{fid}/saved/{rid}").content == b"%PDF-1.4 legacy report"
    second = mig.migrate(root)  # running it again changes nothing
    assert second["copied"] == 0 and second["already_in_database"] == 2
    third = mig.migrate(root, delete_local=True)
    assert third["deleted_local"] == 2 and not (root / "documents" / f"{fid}.pdf").exists() and stray.exists()  # unmatched files are never deleted


def test_a_local_file_is_kept_when_its_database_copy_cannot_be_verified(client, tmp_path, monkeypatch):
    mig = _load_migrator()
    fid, _ = new_doc(client)
    with session.session_scope() as s:
        s.execute(sa.delete(FileObject).where(FileObject.document_id == uuid.UUID(fid)))
    root = tmp_path / "old"
    (root / "documents").mkdir(parents=True)
    f = root / "documents" / f"{fid}.pdf"
    f.write_bytes(b"%PDF-1.4 precious")
    monkeypatch.setattr(filestore.DatabaseFileStore, "read", lambda self, key: b"something else")
    res = mig.migrate(root, delete_local=True)
    assert res["failed"] == 1 and res["deleted_local"] == 0 and f.exists()
