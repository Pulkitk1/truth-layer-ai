"""A realistic verified document for PDF-report tests.

TEST DATA ONLY: it imitates saved verification results so the report builder can be tested without
calling Groq or Tavily. It is never used by the application.
"""
from app import storage
from tests.test_verify import FakeLLM, claim, setup, src, verdict

LONG_URL_PATH = "reports/" + "very-long-path-segment/" * 12 + "final-report-2024-with-a-really-long-slug-name.html?utm_source=newsletter&id=1234567890&ref=abcdefghijklmnopqrstuvwxyz"
UNBROKEN = "SUPERCALIFRAGILISTICEXPIALIDOCIOUS" * 4  # 136 characters, no spaces

LONG_CLAIM = (
    "Between 2015 and 2023 the company expanded its payments network across more than forty cities, processed over "
    "three billion transactions with a combined value of roughly ₹4.2 lakh crore, and reduced its average failed-transaction "
    "rate from 4.1 percent to 0.9 percent, according to figures it presented to investors at the annual general meeting. "
) * 3
LONG_EXPLANATION = (
    "The collected sources describe the same programme in different terms, so each figure in the claim was compared "
    "separately. The transaction volume matches the company's own filing, while the transaction value is described only "
    "in a trade-press summary that does not cite a primary source. The failure-rate improvement is confirmed by two "
    "independent articles but with a different end date. Taken together the evidence supports the direction of the claim "
    "but not every exact figure. "
) * 4

CLAIMS = [
    claim(1, "The Eiffel Tower was completed in 1889.", page=1),
    claim(2, "Tesla reported 2023 revenue of $96.8 billion.", page=2),
    claim(3, "A failed UPI transfer of ₹500 is refunded with ₹50 daily compensation — “automatically”.", page=3),
    claim(4, "The Great Wall of China is visible from the Moon with the naked eye.", page=5),
    claim(5, "Analysts predict that India will have 1 billion smartphone users by 2030.", page=6),
    claim(6, "For example, Priya sends ₹500 by UPI and it is reversed within 3 working days.", page=7),
    claim(7, LONG_CLAIM.strip()[:900], page=8),
    claim(8, "Solar capacity grew 40 percent last year across all member states.", page=9),
    claim(9, f"The identifier {UNBROKEN} is the official protocol name.", page=10),
    claim(10, "Société Générale reported €2.1bn profit; 日本語 text and naïve café £ ¥ symbols.", page=11),
    claim(11, "Global EV sales were 14 million in 2023.", page=12),
    claim(12, "The study surveyed 2,000 respondents.", page=13),
]
CATS = ["date_timeline", "financial", "financial", "scientific", "statistics", "other", "company", "statistics", "technical", "company", "market", "demographic"]
for c, cat in zip(CLAIMS, CATS):
    c["category"] = cat
CLAIMS[2]["value"], CLAIMS[2]["unit"], CLAIMS[2]["time_period"] = "50", "rupees per day", "2024"

EVIDENCE = {
    "claim_001": [src("history.com", "web", "eiffel", date="2024-03-31"), src("en.wikipedia.org", "reference", "Eiffel_Tower"), src("toureiffel.paris", "web", "history", date="2023-05-02"), src("extra-uncited.example.org", "web", "unused")],
    "claim_002": [src("sec.gov", "government", "tsla-10k", date="2024-01-29"), src("ir.tesla.com", "web", "10k")],
    "claim_003": [src("npci.org.in", "institution", "circular", date="2023-08-11", content="Compensation of ₹100 per day of delay applies."), src("rbi.org.in", "institution", "td-framework")],
    "claim_004": [src("nasa.gov", "government", "great-wall", date="2005-05-01"), src("snopes.com", "news", "wall")],
    "claim_005": [src("tsscindia.com", "web", "forecast")],
    "claim_006": [src("npci.org.in", "institution", "upi-help"), src("razorpay.com", "web", "refunds")],
    "claim_007": [src("economictimes.indiatimes.com", "news", "payments-expansion"), src("livemint.com", "news", "network", date="2024-06-12")],
    "claim_008": [src("iea.org", "institution", "solar", date="2024-02-02", score=0.9, content="Solar capacity grew by 25% in 2023."), src("irena.org", "institution", "capacity-2024")],
    "claim_009": [src("w3.org", "institution", LONG_URL_PATH, date="2022-11-01"), src("ietf.org", "institution", "rfc")],
    "claim_010": [src("reuters.com", "news", "societe-generale-results")],
    "claim_011": [src("iea.org", "institution", "ev-outlook-2024"), src("reuters.com", "news", "ev-sales")],
    "claim_012": [src("nature.com", "research", "survey")],
}
# claim_012: missing optional metadata (no title, no date, no relevance text)
EVIDENCE["claim_012"][0]["title"] = ""
# claim_010: markup in an untrusted title must be shown literally, never interpreted
EVIDENCE["claim_010"][0]["title"] = "Q&A <b>results</b> & <script>alert(1)</script> €"
# a non-http URL must never become a link
EVIDENCE["claim_005"].append(dict(src("evil.example", "web", "x"), url="javascript:alert(1)", title="Do not link me"))

LONG_EXPL = LONG_EXPLANATION.strip()[:1900]

REPLIES = {
    "claim_001": verdict("VERIFIED", sup=(1, 2, 3), conf=92, expl="All sources agree that construction finished in March 1889."),
    "claim_002": verdict("VERIFIED", sup=(1, 2), conf=95, expl="The SEC filing states total 2023 revenue of $96.77 billion."),
    "claim_003": verdict("INACCURATE", sup=(), con=(1, 2), conf=82, corrected="Under the RBI framework the compensation is ₹100 per day of delay — not ₹50.", corrected_value="₹100", unit="INR per day", reference_period="2023", correction_explanation="The RBI framework sets ₹100 per day.", expl="The compensation rate in the claim is outdated."),
    "claim_004": verdict("FALSE", sup=(), con=(1, 2), conf=96, corrected="The Great Wall is not visible from the Moon with the naked eye.", expl="NASA states the wall cannot be seen from the Moon."),
    "claim_005": verdict("UNVERIFIED", sup=(), conf=30, ctype="prediction", expl="This is a forecast, so it cannot be confirmed as a fact."),
    "claim_006": verdict("VERIFIED", sup=(1, 2), conf=90, ctype="factual", expl="General refund rules are described, but this is a worked example."),
    "claim_007": verdict("VERIFIED", sup=(1, 2), conf=88, expl=LONG_EXPL),
    "claim_008": verdict("INACCURATE", sup=(), con=(1, 2), conf=84, corrected="Solar capacity grew about 25 percent.", corrected_value="25%", reference_period="2023", expl=LONG_EXPL),
    "claim_009": verdict("FALSE", sup=(), con=(1, 2), conf=91, corrected="The official name is different.", expl="The identifier does not appear in the standard."),
    "claim_010": verdict("VERIFIED", sup=(1,), conf=80, expl="Reuters reports the profit figure."),
    "claim_011": verdict("UNVERIFIED", sup=(1,), con=(2,), conf=40, expl="The IEA and Reuters report different totals; the conflict cannot be resolved."),
    "claim_012": verdict("VERIFIED", sup=(1,), conf=75, expl="The paper reports 2,000 respondents."),
}
# claim_012: a supporting source with no relevance text
REPLIES["claim_012"]["supporting_sources"] = [{"source": 1}]


def make_big_doc(client, monkeypatch, claims=None, evidence=None, replies=None) -> str:
    """Create a document, then run every claim through the real verify endpoint with a mocked AI."""
    claims = CLAIMS if claims is None else claims
    fid = setup(client, claims, EVIDENCE if evidence is None else evidence)
    FakeLLM(monkeypatch, REPLIES if replies is None else replies)
    for c in claims:
        r = client.post("/api/claims/verify", json={"file_id": fid, "claim_ids": [c["claim_id"]]})
        assert r.status_code == 200, r.text
    return fid


def expected_counts(claims=None) -> dict[str, int]:
    """Verdict counts as produced by the fixture (not read back from the app)."""
    return {"VERIFIED": 5, "INACCURATE": 2, "FALSE": 2, "UNVERIFIED": 3}


__all__ = ["CLAIMS", "EVIDENCE", "REPLIES", "make_big_doc", "expected_counts", "storage"]
