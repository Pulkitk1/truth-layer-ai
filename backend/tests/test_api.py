import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return TestClient(main.app)


def make_pdf(pages: list[str], password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    if password:
        data = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password
        )
    else:
        data = doc.tobytes()
    doc.close()
    return data


def make_scanned_pdf() -> bytes:
    """A page containing only an image (no text layer)."""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(72, 72, 272, 272), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, data: bytes, name="test.pdf", ctype="application/pdf"):
    return client.post("/api/upload", files={"file": (name, data, ctype)})


def extract(client, file_id):
    return client.post("/api/extract", json={"file_id": file_id})


def test_valid_upload_and_extract(client):
    data = make_pdf(["Hello TruthLayer"])
    r = upload(client, data)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "test.pdf"
    assert body["file_size"] == len(data)
    assert body["upload_status"] == "uploaded"
    assert len(body["file_id"]) == 32

    e = extract(client, body["file_id"])
    assert e.status_code == 200
    j = e.json()
    assert j["extraction_status"] == "success"
    assert j["total_pages"] == 1
    assert j["pages"][0]["page_number"] == 1
    assert "Hello TruthLayer" in j["pages"][0]["extracted_text"]
    assert j["ocr_required"] is False


def test_multi_page_preserves_page_numbers(client):
    r = upload(client, make_pdf(["Page one text", "Page two text", "Page three text"]))
    j = extract(client, r.json()["file_id"]).json()
    assert j["total_pages"] == 3
    assert [p["page_number"] for p in j["pages"]] == [1, 2, 3]
    assert "Page two text" in j["pages"][1]["extracted_text"]


def test_partial_empty_page_detected(client):
    r = upload(client, make_pdf(["Has text", "", "More text"]))
    j = extract(client, r.json()["file_id"]).json()
    assert j["extraction_status"] == "partial"
    assert j["empty_pages"] == [2]
    assert j["pages"][1]["is_empty"] is True


def test_blank_pdf_reports_no_text(client):
    r = upload(client, make_pdf(["", ""]))
    j = extract(client, r.json()["file_id"]).json()
    assert j["extraction_status"] == "no_text"
    assert j["ocr_required"] is True
    assert j["empty_pages"] == [1, 2]


def test_scanned_pdf_requires_ocr(client):
    r = upload(client, make_scanned_pdf())
    j = extract(client, r.json()["file_id"]).json()
    assert j["extraction_status"] == "no_text"
    assert j["ocr_required"] is True
    assert "OCR" in j["message"]


def test_rejects_non_pdf_extension(client):
    r = upload(client, b"hello", name="notes.txt", ctype="text/plain")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_file_type"


def test_rejects_fake_pdf_content(client):
    r = upload(client, b"this is not a pdf at all", name="fake.pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_pdf"


def test_rejects_empty_file(client):
    r = upload(client, b"", name="empty.pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_file"


def test_rejects_oversized_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    r = upload(client, make_pdf(["x" * 5000]))
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "file_too_large"
    assert list(tmp_path.glob("*.pdf")) == []  # partial file cleaned up


def test_corrupted_pdf(client):
    data = b"%PDF-1.7\n" + b"garbage bytes that are not a real pdf structure" * 20
    r = upload(client, data)
    assert r.status_code == 200  # header is valid; failure surfaces on extract
    e = extract(client, r.json()["file_id"])
    assert e.status_code == 422
    assert e.json()["detail"]["code"] == "corrupted_pdf"


def test_truncated_pdf(client):
    data = make_pdf(["Some text", "More text"])
    r = upload(client, data[: len(data) // 2])
    e = extract(client, r.json()["file_id"])
    assert e.status_code == 422 or e.json()["total_pages"] >= 0  # must not crash (no 500)


def test_password_protected_pdf(client):
    r = upload(client, make_pdf(["secret"], password="pw123"))
    e = extract(client, r.json()["file_id"])
    assert e.status_code == 422
    assert e.json()["detail"]["code"] == "password_protected"


def test_extract_unknown_id(client):
    e = extract(client, "a" * 32)
    assert e.status_code == 404


def test_extract_rejects_path_traversal_id(client):
    e = extract(client, "../../etc/passwd")
    assert e.status_code == 404


def test_delete_file(client):
    r = upload(client, make_pdf(["bye"]))
    fid = r.json()["file_id"]
    assert client.delete(f"/api/files/{fid}").status_code == 200
    assert extract(client, fid).status_code == 404


def test_filename_path_is_sanitised(client):
    r = upload(client, make_pdf(["x"]), name="../../evil/name.pdf")
    assert r.json()["filename"] == "name.pdf"
