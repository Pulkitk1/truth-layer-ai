"""Fake-statistic detection and correct-fact generation. Groq and Tavily are mocked: the evidence below is test data,
not real research. The tests check that corrections are used only when a cited source contains the figure."""
import io

import pytest
from fastapi.testclient import TestClient

from app import grounding, main
from tests.test_verify import FakeLLM, claim, client, one, setup, src, verdict  # noqa: F401


def text_of_pdf(data: bytes) -> str:
    import fitz

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(p.get_text() for p in doc)


def case(client, monkeypatch, text, evidence, reply, **claim_kw):
    c = claim(1, text, page=2, **claim_kw)
    fid = setup(client, [c], {"claim_001": evidence})
    FakeLLM(monkeypatch, {"claim_001": reply})
    return fid, one(client, fid)


# ---------- the ten scenarios ----------

def test_1_completely_false_population_gets_the_real_figure(client, monkeypatch):
    ev = [
        src("data.worldbank.org", "institution", content="India population, total: 1,428,627,663 (2023).", date="2024-07-01"),
        src("censusindia.gov.in", "government", content="The population of India is about 1.43 billion."),
    ]
    _, r = case(
        client, monkeypatch, "India's population is 2 billion.", ev,
        verdict("FALSE", sup=(), con=(1, 2), conf=96, corrected="India's population was about 1.43 billion in 2023.",
                original_value="2 billion", corrected_value="1.43 billion", unit="people", reference_period="2023",
                correction_explanation="The World Bank reports 1,428,627,663 people for 2023.", expl="2 billion is far above official counts."),
    )
    assert r["verification_status"] == "FALSE" and r["correction_status"] == "confirmed"
    assert r["original_claim"] == "India's population is 2 billion." and r["original_value"] == "2 billion"
    assert r["corrected_value"] == "1.43 billion" and r["unit"] == "people" and r["reference_period"] == "2023"
    assert r["correction_explanation"] and r["pdf_page"] == 2
    src0 = r["contradicting_sources"][0]
    assert src0["url"] == "https://data.worldbank.org/p" and "1,428,627,663" in src0["snippet"]


def test_2_outdated_population_is_inaccurate_with_the_current_figure(client, monkeypatch):
    ev = [src("un.org", "institution", content="World population reached 8.1 billion in 2024.", date="2024-11-01")]
    _, r = case(
        client, monkeypatch, "The world population is 7 billion.", ev,
        verdict("INACCURATE", sup=(), con=(1,), conf=88, corrected="The world population is about 8.1 billion (2024).",
                corrected_value="8.1 billion", reference_period="2024", expl="7 billion was reached around 2011."),
    )
    assert r["verification_status"] == "INACCURATE" and r["correction_status"] == "confirmed"
    assert r["corrected_value"] == "8.1 billion" and r["reference_period"] == "2024"


def test_3_wrong_market_size_is_corrected(client, monkeypatch):
    ev = [src("statista.example", "news", content="The market was worth $45 billion in 2023."), src("gartner.example", "institution", content="2023 revenue reached $45 billion.")]
    _, r = case(
        client, monkeypatch, "The market was worth $200 billion in 2023.", ev,
        verdict("INACCURATE", sup=(), con=(1, 2), conf=85, corrected="The market was worth about $45 billion in 2023.",
                corrected_value="$45 billion", unit="USD", reference_period="2023"),
    )
    assert r["correction_status"] == "confirmed" and r["corrected_value"] == "$45 billion"


def test_4_wrong_company_revenue_is_corrected(client, monkeypatch):
    ev = [src("sec.gov", "government", content="Total revenues for fiscal 2023 were $96.77 billion.")]
    _, r = case(
        client, monkeypatch, "Tesla's 2023 revenue was $150 billion.", ev,
        verdict("FALSE", sup=(), con=(1,), conf=94, corrected="Tesla reported revenue of $96.77 billion in 2023.", corrected_value="$96.77 billion", unit="USD", reference_period="FY2023"),
    )
    assert r["verification_status"] == "FALSE" and r["corrected_value"] == "$96.77 billion"


def test_5_inaccurate_percentage_is_corrected(client, monkeypatch):
    ev = [src("who.int", "institution", content="Global adult obesity prevalence was 16% in 2022."), src("nih.gov", "government", content="About 16 percent of adults.")]
    _, r = case(
        client, monkeypatch, "60% of adults worldwide are obese.", ev,
        verdict("FALSE", sup=(), con=(1, 2), conf=93, corrected="About 16% of adults were obese in 2022.", corrected_value="16%", unit="percent", reference_period="2022"),
    )
    assert r["correction_status"] == "confirmed" and r["corrected_value"] == "16%"


def test_6_wrong_historical_date_must_match_exactly(client, monkeypatch):
    ev = [src("archives.gov", "government", content="India became independent on 15 August 1947.")]
    _, ok = case(
        client, monkeypatch, "India became independent in 1950.", ev,
        verdict("FALSE", sup=(), con=(1,), conf=95, corrected="India became independent in 1947.", corrected_value="1947", reference_period="1947"),
    )
    assert ok["correction_status"] == "confirmed" and ok["corrected_value"] == "1947"


def test_6b_a_year_close_to_the_source_year_is_not_accepted(client, monkeypatch):
    ev = [src("archives.gov", "government", content="India became independent on 15 August 1947.")]
    _, r = case(
        client, monkeypatch, "India became independent in 1950.", ev,
        verdict("FALSE", sup=(), con=(1,), conf=95, corrected="India became independent in 1948.", corrected_value="1948"),
    )
    assert r["correction_status"] == "not_confirmed" and r["corrected_value"] is None and r["corrected_claim"] is None
    assert any("does not appear in the cited sources" in a for a in r["adjustments"])


def test_7_a_correct_statement_is_verified_with_no_correction(client, monkeypatch):
    ev = [src("nasa.gov", "government", content="Earth orbits the Sun once every 365.25 days."), src("esa.int", "institution")]
    _, r = case(
        client, monkeypatch, "Earth takes about 365 days to orbit the Sun.", ev,
        verdict("VERIFIED", sup=(1, 2), conf=95, corrected="365 days", corrected_value="365", reference_period="now"),
    )
    assert r["verification_status"] == "VERIFIED" and r["correction_status"] == "not_applicable"
    assert r["corrected_claim"] is None and r["corrected_value"] is None and r["reference_period"] is None


def test_8_a_hypothetical_example_gets_no_correction(client, monkeypatch):
    ev = [src("rbi.org.in", "government", content="Compensation is ₹100 per day.")]
    _, r = case(
        client, monkeypatch, "For example, if Rahul's refund of ₹500 is late by 3 days he receives ₹150.", ev,
        verdict("INACCURATE", sup=(), con=(1,), conf=80, ctype="hypothetical", corrected="₹300", corrected_value="₹300"),
    )
    assert r["verification_status"] == "UNVERIFIED" and r["claim_type"] == "hypothetical"
    assert r["corrected_value"] is None and r["correction_status"] == "not_applicable"


def test_9_conflicting_sources_do_not_produce_a_forced_verdict(client, monkeypatch):
    ev = [src("iea.org", "institution", content="EV sales: 14 million."), src("reuters.com", "news", content="EV sales: 13 million.")]
    _, r = case(
        client, monkeypatch, "EV sales were 10 million in 2023.", ev,
        verdict("UNVERIFIED", sup=(1,), con=(2,), conf=40, expl="Sources report different totals; the conflict cannot be resolved."),
    )
    assert r["verification_status"] == "UNVERIFIED" and r["corrected_value"] is None and r["correction_status"] == "not_applicable"


def test_10_insufficient_evidence_is_unverified_and_invents_nothing(client, monkeypatch):
    _, r = case(client, monkeypatch, "The company has 4,200 employees.", [], verdict("FALSE", corrected="5,000", corrected_value="5,000"))
    assert r["verification_status"] == "UNVERIFIED" and r["corrected_value"] is None and r["confidence_score"] == 0


# ---------- never invent a correction ----------

def test_a_fabricated_correction_is_discarded_but_the_verdict_stays(client, monkeypatch):
    ev = [src("who.int", "institution", content="Prevalence was 16% in 2022."), src("nih.gov", "government", content="Roughly 16 percent.")]
    _, r = case(
        client, monkeypatch, "60% of adults are obese.", ev,
        verdict("FALSE", sup=(), con=(1, 2), conf=95, corrected="42% of adults are obese.", corrected_value="42%", correction_explanation="invented"),
    )
    assert r["verification_status"] == "FALSE" and r["correction_status"] == "not_confirmed"
    assert r["corrected_claim"] is None and r["corrected_value"] is None and r["correction_explanation"] is None
    assert r["confidence_score"] <= 60 and r["original_claim"] == "60% of adults are obese."


def test_a_wrong_claim_without_any_proposed_correction_says_not_confirmed(client, monkeypatch):
    ev = [src("who.int", "institution", content="No such figure is reported."), src("nih.gov", "government")]
    _, r = case(client, monkeypatch, "A fake statistic of 77%.", ev, verdict("FALSE", sup=(), con=(1, 2), conf=90))
    assert r["verification_status"] == "FALSE" and r["correction_status"] == "not_confirmed"


def test_the_correction_must_come_from_a_cited_source(client, monkeypatch):
    ev = [src("who.int", "institution", content="Prevalence was 16%."), src("nih.gov", "government", content="Other text."), src("blog.example", "community", content="It is 42%.")]
    _, r = case(
        client, monkeypatch, "60% of adults are obese.", ev,
        verdict("FALSE", sup=(), con=(1, 2), conf=95, corrected="42%", corrected_value="42%"),
    )  # 42% only appears in a source that was not cited
    assert r["correction_status"] == "not_confirmed" and r["corrected_value"] is None


def test_old_cached_verdicts_without_corrections_are_rechecked(client, monkeypatch):
    ev = [src("who.int", "institution", content="Prevalence was 16%."), src("nih.gov", "government")]
    c = claim(1, "60% of adults are obese.")
    fid = setup(client, [c], {"claim_001": ev})
    fake = FakeLLM(monkeypatch, {"claim_001": verdict("FALSE", sup=(), con=(1, 2), conf=95, corrected_value="16%", corrected="16%")})
    one(client, fid)
    again = one(client, fid)
    assert again["cached"] is True and len(fake.calls) == 1  # unchanged evidence: cache still used


# ---------- grounding helper ----------

@pytest.mark.parametrize(
    "value,text,expected",
    [
        ("1.43 billion", "population 1,428,627,663 in 2023", True),
        ("1.43 billion", "population 2,000,000,000", False),
        ("17.3%", "grew by 17.3 percent", True),
        ("17.3%", "grew by 71.3%", False),
        ("1947", "independence in 1947", True),
        ("1948", "independence in 1947", False),
        ("₹100", "pays ₹100 per day", True),
        ("Mumbai", "the capital is Mumbai.", True),
        ("Delhi", "the capital is Mumbai.", False),
        ("", "anything 5", False),
        ("14 million", "14 million in 2023", True),
        ("14 million", "13 million in 2023", False),
    ],
)
def test_grounding(value, text, expected):
    assert grounding.grounded(value, [text]) is expected


# ---------- persistence and report ----------

def test_corrections_persist_and_reach_the_report_dashboard_data(client, monkeypatch):
    ev = [src("data.worldbank.org", "institution", content="India population: 1,428,627,663 (2023)."), src("censusindia.gov.in", "government")]
    c = claim(1, "India's population is 2 billion.", page=2)
    fid = setup(client, [c], {"claim_001": ev})
    FakeLLM(monkeypatch, {"claim_001": verdict("FALSE", sup=(), con=(1, 2), conf=96, corrected="About 1.43 billion in 2023.", corrected_value="1.43 billion", unit="people", reference_period="2023", correction_explanation="World Bank figure.")})
    one(client, fid)
    # a fresh read straight from the database (what a page refresh does) still has the correction
    stored = main.storage.load_json(fid, "verify")["results"]["claim_001"]["result"]
    assert stored["corrected_value"] == "1.43 billion" and stored["original_claim"] == "India's population is 2 billion."
    rep = client.get(f"/api/reports/{fid}").json()
    v = rep["claims"][0]["verification"]
    assert rep["claims"][0]["claim_text"] == "India's population is 2 billion."
    assert (v["corrected_value"], v["reference_period"], v["correction_status"]) == ("1.43 billion", "2023", "confirmed")
    assert v["contradicting_sources"][0]["snippet"]


def test_the_pdf_report_shows_original_and_corrected_figures_and_never_invents_them(client, monkeypatch):
    ev = [src("data.worldbank.org", "institution", content="India population: 1,428,627,663 (2023).", date="2024-07-01"), src("censusindia.gov.in", "government")]
    ev2 = [src("who.int", "institution", content="Prevalence 16%."), src("nih.gov", "government")]
    cs = [claim(1, "India's population is 2 billion.", page=2), claim(2, "60% of adults are obese.", page=3)]
    fid = setup(client, cs, {"claim_001": ev, "claim_002": ev2})
    FakeLLM(monkeypatch, {
        "claim_001": verdict("FALSE", sup=(), con=(1, 2), conf=96, corrected="About 1.43 billion in 2023.", corrected_value="1.43 billion", unit="people", reference_period="2023", original_value="2 billion", correction_explanation="World Bank figure."),
        "claim_002": verdict("FALSE", sup=(), con=(1, 2), conf=90, corrected="42%", corrected_value="42%"),  # invented
    })
    for cid in ("claim_001", "claim_002"):
        assert client.post("/api/claims/verify", json={"file_id": fid, "claim_ids": [cid]}).status_code == 200
    r = client.get(f"/api/report/{fid}")
    assert r.status_code == 200, r.text
    text = text_of_pdf(r.content)
    assert "ORIGINAL" in text and "CORRECTED" in text
    assert "India's population is 2 billion." in text and "1.43 billion" in text and "2 billion" in text
    assert "data.worldbank.org" in text and "1,428,627,663" in text  # source and evidence snippet
    assert "42%" not in text.replace("60%", "")  # the invented correction is not printed
    assert "could not be confirmed" in text.lower()


@pytest.mark.parametrize(
    "value,text,expected",
    [
        ("1.46 billion", "Population, total India1.46 World8.22 (2025 billion)", True),  # glued, scale in a header
        ("8.22 billion", "India1.46 World8.22", True),
        ("1.9 billion", "India1.46 World8.22", False),
        ("2%", "a 12% rise", False),  # digits inside another number never match
    ],
)
def test_grounding_handles_scraped_table_text(value, text, expected):
    assert grounding.grounded(value, [text]) is expected


def test_a_scale_word_repeated_in_the_unit_is_removed(client, monkeypatch):
    ev = [src("data.worldbank.org", "institution", content="India population 1.46 billion"), src("un.org", "institution")]
    _, r = case(
        client, monkeypatch, "India's population is 2 billion people.", ev,
        verdict("FALSE", sup=(), con=(1, 2), conf=90, corrected="1.46 billion", corrected_value="1.46 billion", original_value="2 billion", unit="billion people"),
    )
    assert r["unit"] == "people"
