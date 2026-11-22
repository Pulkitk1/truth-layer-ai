"""Results-dashboard data tests (GET /api/reports, POST /api/reports/.../summary). Groq is mocked."""
import json

import pytest
from fastapi.testclient import TestClient

from app import llm, main, storage
from app.llm import LlmError
from tests.test_verify import FakeLLM, claim, setup, src, verdict


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    return TestClient(main.app)


TWO_NEWS = [src("reuters.com", "news"), src("bbc.com", "news")]

CLAIMS = [
    claim(1, "The Eiffel Tower was completed in 1889.", page=1),
    claim(2, "Tesla reported 2023 revenue of $96.8 billion.", page=2),
    claim(3, "Global EV sales were 10 million in 2023.", page=2),
    claim(4, "The Great Wall is visible from the Moon.", page=5),
    claim(5, "India will have 1 billion smartphone users by 2030.", page=7),
    claim(6, "Sales rose sharply last year.", page=9),
]
CLAIMS[1]["category"] = "financial"
CLAIMS[2]["category"] = "market"
CLAIMS[3]["category"] = "scientific"
CLAIMS[4]["category"] = "market"
CLAIMS[5]["category"] = "statistics"
CLAIMS[0]["category"] = "date_timeline"

EVIDENCE = {
    "claim_001": TWO_NEWS,
    "claim_002": [src("sec.gov", "government"), src("ir.tesla.com", "web")],
    "claim_003": [src("iea.org", "institution", content="14 million in 2023")],
    "claim_004": [src("nasa.gov", "government", content="The wall is 8 metres wide."), src("snopes.com", "news")],
    "claim_005": [src("random.com")],
    "claim_006": None,  # never searched
}

REPLIES = {
    "claim_001": verdict("VERIFIED", sup=(1, 2), conf=92),
    "claim_002": verdict("VERIFIED", sup=(1, 2), conf=95),
    "claim_003": verdict("INACCURATE", sup=(), con=(1,), conf=80, corrected="Global EV sales were 14 million in 2023.", corrected_value="14 million"),
    "claim_004": verdict("FALSE", sup=(), con=(1, 2), conf=94, corrected="The wall is 8 metres wide.", corrected_value="8 metres"),
    "claim_005": verdict("UNVERIFIED", sup=(), conf=30, ctype="prediction"),
}


def verified_doc(client, monkeypatch) -> str:
    fid = setup(client, CLAIMS, EVIDENCE)
    FakeLLM(monkeypatch, REPLIES)
    for cid in REPLIES:
        r = client.post("/api/claims/verify", json={"file_id": fid, "claim_ids": [cid]})
        assert r.status_code == 200
    return fid


def report(client, fid):
    r = client.get(f"/api/reports/{fid}")
    assert r.status_code == 200, r.text
    return r.json()


# ---------- statistics and data integrity ----------

def test_counts_come_from_the_stored_results(client, monkeypatch):
    rep = report(client, verified_doc(client, monkeypatch))
    assert rep["document_name"] == "d.pdf" and rep["stage"] == "verified"
    n = rep["counts"]
    assert n == {"total": 6, "verified": 2, "inaccurate": 1, "false": 1, "unverified": 1, "pending": 1}
    # the counts must equal a tally of the claims actually returned
    tally = {}
    for c in rep["claims"]:
        tally[c["status"]] = tally.get(c["status"], 0) + 1
    assert tally == {"VERIFIED": 2, "INACCURATE": 1, "FALSE": 1, "UNVERIFIED": 1, "PENDING": 1}
    assert sum(v for k, v in n.items() if k != "total") == n["total"] == len(rep["claims"])


def test_claim_ids_pages_and_text_are_preserved(client, monkeypatch):
    rep = report(client, verified_doc(client, monkeypatch))
    assert [(c["claim_id"], c["page_number"], c["claim_text"]) for c in rep["claims"]] == [
        (c["claim_id"], c["page_number"], c["claim_text"]) for c in CLAIMS
    ]


def test_claim_rows_carry_verdict_fields_and_real_sources(client, monkeypatch):
    rep = report(client, verified_doc(client, monkeypatch))
    by = {c["claim_id"]: c for c in rep["claims"]}
    f = by["claim_004"]
    assert f["status"] == "FALSE" and f["confidence_score"] == 94
    assert f["supporting_count"] == 0 and f["contradicting_count"] == 2
    assert f["verification"]["corrected_claim"] == "The wall is 8 metres wide."
    assert {s["url"] for s in f["verification"]["contradicting_sources"]} <= {s["url"] for s in f["collected_sources"]}
    ok = by["claim_001"]
    assert ok["supporting_count"] == 2 and [s["domain"] for s in ok["collected_sources"]] == ["reuters.com", "bbc.com"]
    assert by["claim_006"]["verification"] is None and by["claim_006"]["confidence_score"] is None
    assert by["claim_006"]["search_status"] is None


def test_category_distribution(client, monkeypatch):
    rep = report(client, verified_doc(client, monkeypatch))
    cats = {c["category"]: c["count"] for c in rep["categories"]}
    assert cats == {"date_timeline": 1, "financial": 1, "market": 2, "scientific": 1, "statistics": 1}
    assert sum(cats.values()) == rep["counts"]["total"]
    assert rep["categories"][0]["category"] == "market"  # largest first


def test_stages(client, monkeypatch):
    fid = setup(client, CLAIMS, {})
    rep = report(client, fid)
    assert rep["stage"] == "claims_extracted" and rep["counts"]["pending"] == 6
    fid2 = setup(client, CLAIMS, EVIDENCE)
    rep2 = report(client, fid2)
    assert rep2["stage"] == "evidence_collected" and rep2["counts"]["verified"] == 0


def test_zero_claims(client):
    rep = report(client, setup(client, [], {}))
    assert rep["counts"]["total"] == 0 and rep["claims"] == [] and rep["categories"] == []
    assert "No factual claims" in rep["summary"]["text"]


def test_changed_evidence_makes_a_verdict_stale(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    data = storage.load_json(fid, "search")
    data["results"]["claim_001"]["sources"][0]["content"] = "something new"
    storage.save_json(fid, "search", data)
    rep = report(client, fid)
    c = next(c for c in rep["claims"] if c["claim_id"] == "claim_001")
    assert c["status"] == "PENDING" and c["stale"] is True and c["verification"] is None
    assert any("new evidence" in w for w in rep["warnings"])
    assert rep["counts"]["verified"] == 1 and rep["counts"]["pending"] == 2


def test_model_change_does_not_hide_verdicts(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    monkeypatch.setenv("GROQ_MODEL", "another-model")
    assert report(client, fid)["counts"]["verified"] == 2


def test_unknown_and_unextracted_documents(client):
    assert client.get(f"/api/reports/{'a' * 32}").status_code == 404
    assert client.get("/api/reports/not-a-valid-id").status_code == 404
    from tests.test_api import make_pdf

    fid = client.post("/api/upload", files={"file": ("d.pdf", make_pdf(["x"]), "application/pdf")}).json()["file_id"]
    r = client.get(f"/api/reports/{fid}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "claims_not_extracted"


# ---------- document summary ----------

def test_template_summary_matches_counts_and_lists_investigation_items(client, monkeypatch):
    s = report(client, verified_doc(client, monkeypatch))["summary"]
    assert s["text"].startswith("6 claims analysed: 2 verified")
    assert "1 inaccurate" in s["text"] and "1 false" in s["text"] and "1 unverified" in s["text"]
    assert s["text"].endswith("1 not verified yet.")
    items = {i["claim_id"]: i for i in s["needs_investigation"]}
    assert set(items) == {"claim_005", "claim_006"}
    assert items["claim_005"]["reason"] == "A forecast, so it cannot be confirmed as a fact."
    assert items["claim_006"]["reason"] == "Not verified yet."
    assert [i["claim_id"] for i in s["needs_investigation"]] == ["claim_005", "claim_006"]  # unverified before pending
    assert s["narrative"] is None


def test_low_confidence_verdicts_need_investigation(client, monkeypatch):
    fid = setup(client, CLAIMS[:1], {"claim_001": TWO_NEWS})
    FakeLLM(monkeypatch, {"claim_001": verdict("VERIFIED", sup=(1, 2), conf=35)})
    client.post("/api/claims/verify", json={"file_id": fid})
    items = report(client, fid)["summary"]["needs_investigation"]
    assert [i["claim_id"] for i in items] == ["claim_001"] and "limited evidence" in items[0]["reason"]


class SummaryLLM:
    def __init__(self, monkeypatch, narrative=None, exc=None):
        self.calls = []
        self.narrative, self.exc = narrative, exc
        monkeypatch.setattr(llm, "complete", self)

    def __call__(self, messages):
        self.calls.append(messages)
        if self.exc:
            raise self.exc
        return json.dumps({"narrative": self.narrative})


GOOD = "Two claims are supported, one is inaccurate and one is false. The forecast and the vague sales claim need more investigation."


def test_ai_narrative_is_generated_cached_and_shown_on_get(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    fake = SummaryLLM(monkeypatch, GOOD)
    r = client.post(f"/api/reports/{fid}/summary")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["narrative"] == GOOD and s["narrative_error"] is None and s["narrative_model"] == "test-model"
    assert s["text"].startswith("6 claims analysed")  # the template summary is still there
    prompt = fake.calls[0][1]["content"]
    assert "claim_004 | FALSE" in prompt and "Counts: total 6, verified 2" in prompt
    assert "untrusted data" in fake.calls[0][0]["content"] and "Do NOT add new facts" in fake.calls[0][0]["content"]
    client.post(f"/api/reports/{fid}/summary")
    assert len(fake.calls) == 1  # cached
    assert report(client, fid)["summary"]["narrative"] == GOOD and len(fake.calls) == 1  # GET never calls the AI
    client.post(f"/api/reports/{fid}/summary?refresh=true")
    assert len(fake.calls) == 2


def test_narrative_with_invented_numbers_is_discarded(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    SummaryLLM(monkeypatch, "Nine claims were supported and 87% were accurate.")
    s = client.post(f"/api/reports/{fid}/summary").json()["summary"]
    assert s["narrative"] is None and "not in the results" in s["narrative_error"]
    assert s["text"].startswith("6 claims analysed")


def test_narrative_failures_fall_back_to_the_template(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    SummaryLLM(monkeypatch, exc=LlmError("groq_timeout", "The Groq request timed out.", 504))
    r = client.post(f"/api/reports/{fid}/summary")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["narrative"] is None and s["narrative_error"] == "The Groq request timed out."
    assert s["text"].startswith("6 claims analysed")
    monkeypatch.setattr(llm, "complete", lambda m: "not json")
    assert client.post(f"/api/reports/{fid}/summary").json()["summary"]["narrative_error"]


def test_no_narrative_before_verification(client, monkeypatch):
    fid = setup(client, CLAIMS, EVIDENCE)
    fake = SummaryLLM(monkeypatch, GOOD)
    s = client.post(f"/api/reports/{fid}/summary").json()["summary"]
    assert s["narrative"] is None and "Verify the claims first" in s["narrative_error"] and fake.calls == []


def test_verdict_change_invalidates_cached_narrative(client, monkeypatch):
    fid = verified_doc(client, monkeypatch)
    fake = SummaryLLM(monkeypatch, GOOD)
    client.post(f"/api/reports/{fid}/summary")
    FakeLLM(monkeypatch, {"claim_006": verdict("UNVERIFIED", sup=(), conf=10)})
    data = storage.load_json(fid, "search")
    data["results"]["claim_006"] = dict(data["results"]["claim_001"], claim_id="claim_006", claim_text=CLAIMS[5]["claim_text"])
    storage.save_json(fid, "search", data)
    client.post("/api/claims/verify", json={"file_id": fid, "claim_ids": ["claim_006"]})
    assert report(client, fid)["summary"]["narrative"] is None  # verdicts changed: old text no longer matches
    assert len(fake.calls) == 1


def test_deleting_a_document_removes_its_summary_too(client, monkeypatch, tmp_path):
    fid = verified_doc(client, monkeypatch)
    SummaryLLM(monkeypatch, GOOD)
    client.post(f"/api/reports/{fid}/summary")
    assert storage.load_json(fid, "summary")["narrative"]  # the summary is saved in the database
    client.delete(f"/api/files/{fid}")
    assert storage.load_json(fid, "summary") is None and storage.load_meta(fid) is None
    assert list(tmp_path.glob(f"{fid}*")) == []
