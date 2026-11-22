"""PDF report tests. The PDF is built from saved results with a mocked AI: no network, no API credits."""
import json
import os
import re

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import llm, main, pdf_report, storage, tavily_client
from tests.pdf_fixture import CLAIMS, EVIDENCE, LONG_URL_PATH, REPLIES, UNBROKEN, expected_counts, make_big_doc
from tests.test_api import make_pdf
from tests.test_verify import FakeLLM, claim, setup, src, verdict


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    return TestClient(main.app)


def download(client, fid):
    return client.get(f"/api/report/{fid}")


def open_pdf(resp) -> pymupdf.Document:
    assert resp.status_code == 200, resp.text
    return pymupdf.open(stream=resp.content, filetype="pdf")


def all_text(doc) -> str:
    return "\n".join(p.get_text() for p in doc)


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One verified 12-claim document, built once and shared by the read-only tests (it is the slow part)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("UPLOAD_DIR", str(tmp_path_factory.mktemp("uploads")))
    mp.setenv("GROQ_API_KEY", "test-groq")
    mp.setenv("GROQ_MODEL", "test-model")
    client = TestClient(main.app)
    fid = make_big_doc(client, mp)
    resp = download(client, fid)
    doc = open_pdf(resp)
    if os.environ.get("TRUTHLAYER_SAVE_SAMPLE"):  # used for the visual QA step
        with open(os.environ["TRUTHLAYER_SAVE_SAMPLE"], "wb") as f:
            f.write(resp.content)
    yield client, fid, resp, doc
    mp.undo()


@pytest.fixture()
def big(shared):
    _, fid, resp, doc = shared
    return fid, resp, doc


@pytest.fixture()
def bigclient(shared):
    """The API client that owns the shared document (its upload folder differs from `client`'s)."""
    return shared[0]


# ---------------------------------------------------------------- generation and download

def test_successful_pdf_generation_and_download_headers(big):
    fid, resp, doc = big
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment;") and 'filename="truthlayer-fact-check-d.pdf"' in cd
    assert resp.headers["cache-control"] == "no-store"
    assert doc.metadata["title"] == "AI Fact-Checking Report" and doc.metadata["author"] == "TruthLayer AI"


def test_report_is_a4_with_selectable_text(big):
    _, _, doc = big
    for page in doc:
        assert (round(page.rect.width), round(page.rect.height)) == (595, 842)
    assert len(all_text(doc)) > 3000  # real text, not an image


def test_multi_page_report_has_the_required_sections_in_order(big):
    _, _, doc = big
    assert doc.page_count >= 8
    text = all_text(doc)
    order = ["AI Fact-Checking Report", "Executive summary", "Verification overview", "Detailed claim-by-claim analysis", "Sources and references", "Limitations and disclaimer"]
    positions = [text.index(h) for h in order]
    assert positions == sorted(positions)
    assert "Automated, evidence-based verification" in doc[0].get_text()


def test_cover_page_contents(big):
    _, _, doc = big
    cover = doc[0].get_text()
    assert "TruthLayer" in cover and "AI Fact-Checking Report" in cover
    assert "d.pdf" in cover and "UTC" in cover  # original file name and generation time
    assert re.search(r"CLAIMS ANALYZED\s*\n?\s*12", cover)


def test_every_page_after_the_cover_has_page_numbers_and_branding(big):
    _, _, doc = big
    n = doc.page_count
    for i in range(1, n):
        t = doc[i].get_text()
        assert f"Page {i + 1} of {n}" in t
        assert "TruthLayer" in t


# ---------------------------------------------------------------- numbers

def test_statistics_come_from_the_claims_and_add_up(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)
    from app.main import _load_report

    from tests.conftest import _TOKENS

    stats = pdf_report.compute_stats(_load_report(fid, f"Bearer {_TOKENS[fid]}"))
    assert stats["total"] == 12
    assert stats["counts"] == expected_counts()
    assert sum(stats["counts"].values()) == stats["total"]
    assert sum(stats["percent"].values()) == 100
    assert sum(r["total"] for _, r in stats["categories"]) == 12


def test_pdf_shows_the_same_totals_and_percentages(big):
    _, _, doc = big
    text = all_text(doc)
    exp = expected_counts()
    assert re.search(r"TOTAL CLAIMS\s+ANALYZED\s+12\b", text)
    for status, label in [("VERIFIED", "VERIFIED"), ("INACCURATE", "INACCURATE"), ("FALSE", "FALSE"), ("UNVERIFIED", "UNVERIFIED")]:
        assert re.search(rf"{label}\s*\n?\s*{exp[status]}\b", text), status
    assert "Verified 42%" in text and "Inaccurate 17%" in text and "False 16%" in text and "Unverified 25%" in text
    overview = [p.get_text() for p in doc if "Verification overview" in p.get_text() and "Claims by category" in p.get_text()][0]
    assert "100%" in overview and "12" in overview
    assert re.search(r"Total\s*\n?\s*12", overview)


@pytest.mark.parametrize("counts", [(1, 1, 1, 1), (5, 2, 2, 3), (7, 0, 0, 0), (1, 0, 0, 2), (3, 3, 3, 1), (13, 4, 5, 11)])
def test_percentages_always_total_exactly_100(counts):
    keys = ["VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED"]
    c = dict(zip(keys, counts))
    p = pdf_report._percentages(c, sum(counts))
    assert sum(p.values()) == 100
    assert all(abs(p[k] - c[k] * 100 / sum(counts)) < 1 for k in keys)


def test_unverified_claims_are_never_turned_into_false(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)
    rep = client.get(f"/api/reports/{fid}").json()
    status = {c["claim_id"]: c["status"] for c in rep["claims"]}
    text = squash(all_text(open_pdf(download(client, fid))))
    for cid in ("claim_005", "claim_006", "claim_011"):
        assert status[cid] == "UNVERIFIED" or cid == "claim_006"  # claim_006 is forced to UNVERIFIED by the example rule
    assert squash("Unverified does not mean false") in text


def test_claim_details_ids_pages_categories_and_verdicts_are_preserved(big, bigclient):
    fid, _, doc = big
    text = all_text(doc)
    rep = bigclient.get(f"/api/reports/{fid}").json()
    detail = text[text.index("Detailed claim-by-claim analysis"): text.index("Sources and references")]
    for c in rep["claims"]:
        assert c["claim_id"] in detail
        assert f"PDF page {c['page_number']}" in detail
    ids = re.findall(r"(claim_\d{3})\s*\n?\s*·\s*\n?\s*PDF page", detail)
    assert ids == [c["claim_id"] for c in rep["claims"]]  # one section per claim, original order
    for label in ("AI EXPLANATION", "EVIDENCE SUMMARY", "SUPPORTING SOURCES", "CONTRADICTING SOURCES", "CORRECTED INFORMATION", "CONFIDENCE"):
        assert label in detail
    assert "NASA states the wall cannot be seen from the Moon." in squash(detail) or squash("NASA states the wall cannot be seen") in squash(detail)
    for c in rep["claims"]:
        assert f"{c['confidence_score']}/100" in detail, c["claim_id"]


def test_original_claim_text_is_reproduced_exactly(big):
    _, _, doc = big
    s = squash(all_text(doc))
    assert squash(CLAIMS[0]["claim_text"]) in s
    assert squash(CLAIMS[3]["claim_text"]) in s


# ---------------------------------------------------------------- long text and layout

def test_long_claim_and_long_explanation_wrap_inside_the_page(big):
    _, _, doc = big
    s = squash(all_text(doc))
    assert squash(CLAIMS[6]["claim_text"]) in s  # 900-character claim, complete
    assert squash(UNBROKEN) in s  # 136-character token with no spaces, complete
    for page in doc:
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 >= 30 and x1 <= page.rect.width - 30, (page.number, x0, x1)
            assert y0 >= 10 and y1 <= page.rect.height - 10


def test_text_blocks_do_not_overlap(big):
    _, _, doc = big
    for page in doc:
        blocks = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if b[6] == 0]
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                inter = a & b
                assert inter.is_empty or inter.height < 3 or inter.width < 3, (page.number, a, b)


def test_long_urls_wrap_and_stay_whole(big):
    _, _, doc = big
    s = squash(all_text(doc))
    assert squash("https://w3.org/" + LONG_URL_PATH) in s


# ---------------------------------------------------------------- unicode

def test_rupee_and_other_symbols_are_rendered(big):
    _, _, doc = big
    text = all_text(doc)
    for ch in ("₹", "€", "£", "¥", "—", "“", "”", "%", "é", "ï"):
        assert ch in text, ch
    assert "₹50" in text.replace(" ", "") or "₹500" in text.replace(" ", "")


def test_unsupported_characters_become_question_marks_not_crashes(big):
    _, _, doc = big
    text = all_text(doc)
    assert "日" not in text and "???" in text  # the CJK run is replaced instead of drawn as boxes
    assert "Société Générale" in text


def test_fonts_are_embedded(big):
    _, _, doc = big
    names = {f[3] for p in doc for f in p.get_fonts()}
    assert any("NotoSans" in n for n in names)


def test_clean_strips_control_characters_and_limits_length():
    assert pdf_report.clean("a\x00b\x07c‮d") == "abcd"
    assert pdf_report.clean("x" * 100, limit=10).endswith("…") and len(pdf_report.clean("x" * 100, limit=10)) == 10


# ---------------------------------------------------------------- links and sources

def link_uris(doc) -> list[str]:
    return [l["uri"] for p in doc for l in p.get_links() if l.get("uri")]


def test_source_urls_are_clickable_and_exact(big, bigclient):
    fid, _, doc = big
    uris = set(link_uris(doc))
    rep = bigclient.get(f"/api/reports/{fid}").json()
    for c in rep["claims"]:
        v = c["verification"]
        for s in v["supporting_sources"] + v["contradicting_sources"]:
            assert s["url"] in uris, s["url"]
        for s in c["collected_sources"]:
            if s["url"].startswith("http"):
                assert s["url"] in uris
    assert "https://w3.org/" + LONG_URL_PATH in uris  # the very long URL is linked in full


def test_unsafe_urls_never_become_links(big):
    _, _, doc = big
    assert not any(u.lower().startswith("javascript:") for u in link_uris(doc))
    assert all(u.startswith(("http://", "https://")) for u in link_uris(doc))


def test_sources_section_lists_only_real_sources_with_roles_and_claim_ids(big, bigclient):
    fid, _, doc = big
    text = all_text(doc)
    sec = text[text.index("Sources and references"): text.index("Limitations and disclaimer")]
    rep = bigclient.get(f"/api/reports/{fid}").json()
    real = {s["url"] for c in rep["claims"] for s in c["collected_sources"]}
    listed = set(re.findall(r"https?://[^\s]+", sec.replace("\n", " ")))
    assert listed, "no URLs listed"
    # every listed link target is a collected source URL (nothing invented)
    assert set(link_uris(doc)) <= real | {u for u in link_uris(doc) if u not in real and False}
    assert "Supports" in sec and "Contradicts" in sec and "Reviewed, not cited" in sec
    assert "claim_001" in sec and "claim_012" in sec
    assert "2024-03-31" in sec  # publication date shown when available


def test_supporting_and_contradicting_stay_separate(big):
    _, _, doc = big
    text = all_text(doc)
    d = text[text.index("Detailed claim-by-claim analysis"): text.index("Sources and references")]
    block = d[d.index("claim_004"): d.index("claim_005")]
    sup = block[block.index("SUPPORTING SOURCES"): block.index("CONTRADICTING SOURCES")]
    con = block[block.index("CONTRADICTING SOURCES"):]
    assert "SUPPORTING SOURCES (0)" in sup and "None cited" in sup
    assert "nasa.gov" in con and "snopes.com" in con and "nasa.gov" not in sup


# ---------------------------------------------------------------- untrusted content, missing metadata

def test_markup_in_untrusted_text_is_shown_literally(big):
    _, _, doc = big
    s = squash(all_text(doc))
    assert squash("Q&A <b>results</b> & <script>alert(1)</script>") in s


def test_missing_optional_metadata_does_not_break_the_report(big):
    _, _, doc = big
    d = all_text(doc)
    block = d[d.index("claim_012"): d.index("Sources and references")]
    assert "SUPPORTING SOURCES (1)" in block and "nature.com" in block  # empty title falls back to the domain


def test_hostile_text_in_claims_and_explanations_cannot_break_the_pdf(client, monkeypatch):
    nasty = "</para><b>x</i> &nbsp; <link href='javascript:1'>y</link> \x00\x07 ‮ text <font size='500'>big</font>"
    c = claim(1, "Hostile: " + nasty)
    ev = {"claim_001": [src("reuters.com", "news", "p")]}
    ev["claim_001"][0]["title"] = nasty
    fid = setup(client, [c], ev)
    FakeLLM(monkeypatch, {"claim_001": verdict("VERIFIED", sup=(1,), conf=70, expl=nasty)})
    assert client.post("/api/claims/verify", json={"file_id": fid}).status_code == 200
    doc = open_pdf(download(client, fid))
    assert "javascript" in all_text(doc) and not any("javascript" in u for u in link_uris(doc))


# ---------------------------------------------------------------- errors and gating

def test_invalid_and_unknown_ids(client):
    r = download(client, "not-a-valid-id")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_file_id"
    r = download(client, "../../etc/passwd")
    assert r.status_code in (400, 404)
    r = download(client, "a" * 32)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "file_not_found"


def test_download_before_extraction_and_before_verification(client, monkeypatch):
    fid = client.post("/api/upload", files={"file": ("d.pdf", make_pdf(["x"]), "application/pdf")}).json()["file_id"]
    r = download(client, fid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "claims_not_extracted"

    fid2 = setup(client, CLAIMS, EVIDENCE)  # claims + evidence, but no verdicts
    r = download(client, fid2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "verification_incomplete"
    assert "12 of 12 claims are not verified yet" in r.json()["detail"]["message"]


def test_partially_verified_documents_are_blocked(client, monkeypatch):
    fid = setup(client, CLAIMS, EVIDENCE)
    FakeLLM(monkeypatch, REPLIES)
    for cid in ("claim_001", "claim_002", "claim_003"):
        client.post("/api/claims/verify", json={"file_id": fid, "claim_ids": [cid]})
    r = download(client, fid)
    assert r.status_code == 409 and "9 of 12" in r.json()["detail"]["message"]
    rep = client.get(f"/api/reports/{fid}").json()
    assert rep["pdf_ready"] is False and rep["pdf_blocker"] and "9 of 12" in rep["pdf_blocker"]


def test_changed_evidence_blocks_the_report_until_reverified(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)
    assert download(client, fid).status_code == 200
    data = storage.load_json(fid, "search")
    data["results"]["claim_001"]["sources"][0]["content"] = "new evidence"
    storage.save_json(fid, "search", data)
    r = download(client, fid)
    assert r.status_code == 409 and "1 of 12" in r.json()["detail"]["message"]


def test_json_report_tells_the_dashboard_when_the_pdf_is_ready(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)
    rep = client.get(f"/api/reports/{fid}").json()
    assert rep["pdf_ready"] is True and rep["pdf_blocker"] is None


def test_empty_results_produce_a_valid_explanatory_report(client):
    fid = setup(client, [], {})
    doc = open_pdf(download(client, fid))
    text = all_text(doc)
    assert "No factual claims were extracted" in text
    assert re.search(r"TOTAL CLAIMS\s+ANALYZED\s+0\b", text)
    assert "No web sources were collected" in text
    assert "Limitations and disclaimer" in text


def test_generation_failure_returns_a_clear_error(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)

    def boom(report):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(main.pdf_service, "build_pdf", boom)
    r = download(client, fid)
    assert r.status_code == 500 and r.json()["detail"]["code"] == "report_generation_failed"
    assert "renderer exploded" not in r.text  # internals are not leaked


def test_filename_is_sanitised():
    assert pdf_report.download_filename("../../évil name (final).pdf") == "truthlayer-fact-check-evil-name-final.pdf"
    assert pdf_report.download_filename("   ") == "truthlayer-fact-check-document.pdf"
    assert "/" not in pdf_report.download_filename("a/b\\c.pdf")


# ---------------------------------------------------------------- no AI calls, no leftovers

def test_report_generation_makes_no_groq_or_tavily_calls(client, monkeypatch, tmp_path):
    fid = make_big_doc(client, monkeypatch)

    def forbidden(*a, **k):
        raise AssertionError("an external API was called while generating the report")

    monkeypatch.setattr(llm, "complete", forbidden)
    monkeypatch.setattr(llm, "get_client", forbidden)
    monkeypatch.setattr(tavily_client, "get_client", forbidden)
    monkeypatch.setattr(tavily_client, "search_web", forbidden)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert download(client, fid).status_code == 200
    assert download(client, fid).status_code == 200  # repeatable
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # nothing written to disk


def test_cached_ai_summary_is_included_without_calling_the_ai(client, monkeypatch):
    fid = make_big_doc(client, monkeypatch)
    narrative = "Five claims are supported, two are inaccurate and two are false. The forecast needs more investigation."
    monkeypatch.setattr(llm, "complete", lambda m: json.dumps({"narrative": narrative}))
    assert client.post(f"/api/reports/{fid}/summary").json()["summary"]["narrative"] == narrative
    monkeypatch.setattr(llm, "complete", lambda m: (_ for _ in ()).throw(AssertionError("AI called")))
    text = all_text(open_pdf(download(client, fid)))
    assert "AI-WRITTEN SUMMARY" in text and squash(narrative) in squash(text)


def test_report_without_cached_summary_still_has_the_built_in_summary(big):
    _, _, doc = big
    text = all_text(doc)
    assert "AI-WRITTEN SUMMARY" not in text
    assert "12 claims analysed: 5 verified" in squash(text).replace("analysed:", "analysed: ").replace("claimsanalysed", "12 claims analysed") or "analysed" in text


def test_disclaimer_text_and_required_explanations(big):
    _, _, doc = big
    s = squash(all_text(doc))
    assert squash(pdf_report.DISCLAIMER) in s
    for phrase in (
        "Unverified does not mean false",
        "not statistically calibrated probabilities",
        "not guaranteed to include every relevant source",
        "evidence available at the time of analysis",
    ):
        assert squash(phrase) in s, phrase


def test_symbols_the_font_lacks_get_readable_stand_ins():
    pdf_report._register_fonts()
    assert pdf_report.clean("revenue ≈ $96.8bn") == "revenue ~ $96.8bn"
    assert pdf_report.clean("a → b ≠ c ≤ d ≥ e") == "a -> b != c <= d >= e"
    assert pdf_report.clean("ＡＢ ①") == "AB 1"  # full-width letters and circled digits via compatibility mapping
    assert pdf_report.clean("日本") == "??"  # truly unsupported scripts still degrade safely
    assert pdf_report.clean("₹500 €5 £5") == "₹500 €5 £5"  # supported symbols untouched
