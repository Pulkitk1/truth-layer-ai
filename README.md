# TruthLayer AI

### Don't Just Publish. Verify.

TruthLayer AI is an AI-powered PDF fact-checking application. Upload a document and it automatically extracts the factual claims it makes, searches the live internet for evidence, and flags information that may be inaccurate, outdated or unsupported, so you can fix problems before you publish.

> **Status:** the application is fully built and tested. It is **not publicly deployed yet**; hosting on Render is planned.

---

## The problem

Marketing reports, business documents and research materials often contain statistics that are out of date, figures that are slightly wrong, and claims that nobody can trace to a source. Checking every statement by hand is slow, repetitive and easy to skip when a deadline is close.

TruthLayer AI automates the tedious part. It finds the checkable statements, gathers evidence from the web, and shows you which claims hold up, which need correcting, and which need a human look.

## Key features

- **PDF upload** with automatic text extraction, page by page.
- **AI claim extraction** using Groq: statistics, financial figures, dates, market data, scientific and technical statements, company and demographic facts. Every claim keeps its exact wording and PDF page.
- **Live web research** using Tavily, with sources ranked so government, institutional, research and reputable news sources count for more than blogs and forums.
- **Evidence-based verification** that judges each claim only against the evidence collected for it.
- **Four clear verdicts**: Verified, Inaccurate, False and Unverified, each with a confidence rating that reflects the strength of the evidence.
- **Supporting and contradicting sources** for every verdict, with links and publication dates.
- **Interactive dashboard** with summary cards, charts, search, filters and sorting, an AI-written summary, and a "needs further investigation" list. It works on desktop and mobile.
- **Detailed claim explanations**: the reasoning, the corrected statement when the evidence supports one, and an evidence summary.
- **Downloadable PDF report** with an executive summary, a section for every claim, a sources table and a clear disclaimer.
- **Persistent storage** of documents, results, uploaded PDFs and generated reports in Neon PostgreSQL.
- **Secure document access**: each upload gets its own secret access token, and documents are deleted automatically after a retention period (30 days by default).

## How it works

1. **Upload** a PDF document.
2. **Extract** the text from every page.
3. **Identify** the factual claims in the text using AI.
4. **Search** the internet for evidence about each claim.
5. **Compare** every claim with the evidence that was collected.
6. **Review** the results in the interactive dashboard.
7. **Download** the fact-checking report as a PDF.

## Verification statuses

| Status | Meaning |
| --- | --- |
| **VERIFIED** | Reliable evidence supports the claim. |
| **INACCURATE** | The claim contains incorrect, outdated or misleading information. |
| **FALSE** | Reliable evidence directly contradicts the claim. |
| **UNVERIFIED** | The available evidence is not enough to reach a conclusion. |

A few safeguards keep the verdicts honest. A claim is never marked false just because nothing was found; forecasts and illustrative examples are never declared true or false; and a verdict is only as strong as the sources behind it.

## Technology

| Area | Technology |
| --- | --- |
| Frontend | Next.js, React, TypeScript and Tailwind CSS |
| Backend | Python and FastAPI |
| AI | Groq |
| Web search | Tavily |
| Database and file storage | Neon PostgreSQL |
| PDF processing | PyMuPDF (reading) and ReportLab (reports) |
| Hosting | Render (planned deployment) |

## Good to know

- TruthLayer AI is an aid for reviewers, not a replacement for them. Verdicts depend on the evidence the web search finds, so always read the sources before relying on a result.
- Scanned or image-only PDFs are not supported yet, because there is no text recognition (OCR).

## Documentation

Developer documentation, including setup, configuration, the API, the security model, testing and the Render deployment guide, is in [docs/development.md](docs/development.md).
