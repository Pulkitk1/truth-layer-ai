# TruthLayer AI: Developer Guide

Technical documentation for TruthLayer AI: setup, configuration, API reference, database, security model, Render
deployment and tests. For a product overview, see the [README](../README.md).

> **Status: Step 8D (Render deployment configuration ready, not yet deployed).** PDF upload, text extraction, **AI claim extraction (Groq)**, **live web evidence
> collection (Tavily)**, **AI fact-checking (Groq)**, an **interactive results dashboard** and a **downloadable PDF
> report** work end to end. Each claim gets a verdict of VERIFIED / INACCURATE / FALSE / UNVERIFIED, based only on the
> collected evidence. `/results` shows **real** results for your document; `/results/demo` is a static preview that is
> clearly labeled **DEMO DATA** and has no PDF download. Everything, **including the PDF files**, is saved in **Neon PostgreSQL** (no other storage service), and every document is
> protected by a **secret access token** (see [Security model](#security-model)). `GET /api/health` reports
> `production_ready`, which is `false` until everything production needs is actually in place. `render.yaml` defines both services for [Render](#deploying-on-render); nothing has been deployed yet.

## Contents

- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Setup and run](#setup-and-run)
- [Groq setup (AI claim extraction)](#groq-setup-ai-claim-extraction)
- [Tavily setup (web search for evidence)](#tavily-setup-web-search-for-evidence)
- [AI fact-checking (verification)](#ai-fact-checking-verification)
- [Database (Neon PostgreSQL)](#database-neon-postgresql)
- [Security model](#security-model)
- [Production readiness](#production-readiness)
- [Deploying on Render](#deploying-on-render)
- [Results dashboard (/results)](#results-dashboard-results)
- [PDF report](#pdf-report)
- [Configuration](#configuration)
- [API](#api)
- [Dependency audit](#dependency-audit)
- [Tests](#tests)
- [Try the claims feature manually](#try-the-claims-feature-manually)
- [Try the web search manually](#try-the-web-search-manually)
- [Try the fact-checking manually](#try-the-fact-checking-manually)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)

## Tech stack

- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4, Lucide icons
- **Backend:** Python FastAPI, Uvicorn, PyMuPDF, python-multipart, Pydantic, python-dotenv, Groq SDK, Tavily SDK
- **Database:** Neon PostgreSQL, SQLAlchemy 2.x, Psycopg 3, Alembic
- **File storage:** PDFs and reports are stored in Neon as PostgreSQL `BYTEA` (table `file_objects`); no S3, R2 or disk storage

## Prerequisites

- Node.js 20+
- Python 3.10+

## Setup and run

### 1. Backend (http://localhost:8000)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt       # (use requirements-dev.txt to also get pytest)
copy .env.example .env          # then set GROQ_API_KEY, TAVILY_API_KEY and DATABASE_URL in backend\.env
.\.venv\Scripts\alembic upgrade head   # create the database tables (once, and after pulling new migrations)
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```

macOS/Linux: use `source .venv/bin/activate` and `cp .env.example .env`.

### 2. Frontend (http://localhost:3000)

In a second terminal, from the project root:

```bash
npm install
copy .env.example .env.local    # sets NEXT_PUBLIC_API_URL (default http://localhost:8000)
npm run dev
```

Open http://localhost:3000 → **Start Fact-Checking** → upload a PDF → **Analyze document**.

## Groq setup (AI claim extraction)

1. Create a free API key at https://console.groq.com/keys.
2. In `backend/.env` set:
   ```
   GROQ_API_KEY=gsk_your_key_here
   GROQ_MODEL=openai/gpt-oss-120b
   ```
3. Restart the backend (it reads `.env` at startup).

The key lives only in the backend. Never put it in `.env.local` or any `NEXT_PUBLIC_*` variable, and never commit
`backend/.env` (it is git-ignored). Without a key, the upload and text extraction still work; the claims button
returns a clear "GROQ_API_KEY is not set" error. `GROQ_MODEL` can be any Groq chat model that supports JSON mode.

### How claim extraction works

1. The PDF text is re-read with the existing PyMuPDF extraction, page by page.
2. Pages are grouped into chunks of up to `CLAIM_CHUNK_CHARS` characters (long pages are split on paragraph/sentence
   boundaries). Each chunk keeps its page numbers, and a document needing more than `CLAIM_MAX_CHUNKS` chunks is rejected
   (HTTP 413) rather than silently truncated.
3. Each chunk is sent to Groq in JSON mode. The prompt treats the document as untrusted data and tells the model to
   ignore any instructions inside it.
4. The reply is parsed and validated with Pydantic. Malformed JSON gets one automatic repair retry. Oversized requests
   are split in half and retried.
5. **Grounding:** each claim's text must be found in the PDF page text. The reported page number comes from where the
   text was found, not from the model. Claims that are not in the document are dropped and reported in `warnings`.
6. Duplicates across chunks and pages are removed, and IDs are assigned (`claim_001`, ...).

If some chunks fail (e.g. a timeout) you get the claims from the others with `status: "partial"` and a warning naming the
failed pages. Auth, rate-limit and missing-key errors stop the job immediately.

## Tavily setup (web search for evidence)

1. Create a free API key at https://app.tavily.com.
2. In `backend/.env` set `TAVILY_API_KEY=tvly-...` and restart the backend.

Like the Groq key, it lives only in the backend (never in `.env.local` or `NEXT_PUBLIC_*`, never committed).
Without it, upload, extraction and claim extraction still work; the evidence button shows a clear
"TAVILY_API_KEY is not set" error.

### How evidence collection works

1. `POST /api/claims/extract` now also saves the extracted claims next to the uploaded PDF (same temp folder, same
   expiry), so the search step reuses them instead of re-running the AI. Search requires claims to be extracted first.
2. **Queries:** one focused query per claim. Groq writes them in a single batched call (using the normalized claim,
   category, time period and context, and naming the likely official body, e.g. RBI or WHO). If Groq is unavailable it
   falls back to a rule-based query, shown as "(automatic)".
3. **Search:** one Tavily search per claim, `basic` depth by default (1 credit per search). Set
   `TAVILY_SEARCH_DEPTH=advanced` for deeper results (2 credits). A few junk domains (Pinterest, Quora, Facebook,
   Instagram, TikTok) are excluded.
4. **Ranking:** results are re-ranked as Tavily's relevance score plus a trust bonus by source type: government and
   official institutions, research and `.edu`, reputable news, reference, general web; blogs and forums are penalised.
   Each source is tagged with its type. Duplicate URLs (ignoring `www`, tracking parameters and fragments) are removed
   per claim, and the top `TAVILY_MAX_RESULTS` are kept. Original URLs are preserved exactly; only `http(s)` links are kept.
5. **Credit control:** results are cached per claim (a second click does not search again; "Search again" refreshes),
   identical queries in one run are searched once, and at most `MAX_SEARCH_CLAIMS` claims are searched per document.
   Extra claims are marked `skipped`, never silently dropped.
6. **Failures are recorded per claim** (`search_status`: `completed`, `no_results`, `failed`, `skipped`) with an error
   code and message, and failures are not cached so they can be retried. A rate limit is retried once. A bad key or
   exhausted credits stop the job; claims already searched are kept.
7. Web snippets are untrusted data: shown as plain text, never executed or followed, and labelled "not proof".

## AI fact-checking (verification)

Uses the same Groq key and `GROQ_MODEL`; no extra setup. It needs claims extracted and evidence collected first.

### How it works

1. `POST /api/claims/verify` reads the saved claims and the saved Tavily evidence. **It never searches the web.**
2. Each claim gets one Groq call containing the claim, today's date, and the numbered evidence (title, domain, source
   type, publication date, snippet). The prompt defines the four verdicts, source weighting (government, official
   documents, research, institutions, reputable news, then others), and the special cases below. The model cites
   sources **by number**, so it cannot return a URL that was not collected. Pydantic validates the reply; malformed
   JSON gets one repair retry.
3. The verdict then passes through **safety rules** in code, so a mistaken AI answer cannot overstate the evidence.
   Any change is listed under `adjustments` and shown in the UI:
   - **VERIFIED** needs at least one non-blog supporting source, and is downgraded to UNVERIFIED if an authoritative
     source contradicts the claim.
   - **FALSE** needs a contradicting authoritative source (government, institution, research or news) or two
     independent contradicting sources, and is downgraded if an authoritative source supports the claim.
   - **INACCURATE** needs at least one cited non-blog source for the correction.
   - Predictions, hypothetical or illustrative examples and non-verifiable statements are always UNVERIFIED, and a
     forecast is never marked false because reality differed.
   - Citations to sources that were not in the evidence are discarded; `corrected_claim` is kept only for
     INACCURATE/FALSE.
   - **Confidence** (0-100) is the strength of the evidence, not a probability. It is capped when there is no
     authoritative supporting source (75), only one supporting source (85), contradicting evidence (60), or the
     verdict is UNVERIFIED (50), and at 40 after a downgrade.
4. **No evidence is never FALSE.** If the search found nothing, the claim is UNVERIFIED without calling the AI. If a
   claim was never searched (or its search failed), it is reported as `failed` / `evidence_missing`, not guessed.
5. **Caching:** verdicts are saved per claim with a fingerprint of the claim, model and evidence. Repeated requests
   reuse them (no Groq calls); changing the evidence or model, or `refresh: true`, re-checks. Failures are never cached.
6. A bad key, missing key or rate limit stops the run (finished claims are kept); other failures only fail that claim.

### Groq rate limits

Groq limits **tokens per minute** (for example 8,000 for `openai/gpt-oss-120b` on the free tier) separately from
requests per day, so you can hit "rate limit reached" while your daily allowance is almost untouched. Each fact-check
sends a few thousand tokens, so a burst of them would exceed the minute's budget. The backend therefore:

- makes Groq calls **one at a time** and **paces** them using the remaining-token numbers Groq returns in its response
  headers, waiting just long enough for the budget to refill;
- on a 429, **waits for the time Groq asks for** (`Retry-After`) and retries up to 3 times;
- if it still cannot proceed, says **which limit** was hit and how long to wait. A **daily** limit is reported separately
  (`groq_daily_limit`) because waiting a minute will not help.

The result is slower but reliable: expect roughly 10-30 seconds per claim when verifying many claims on the free tier
(10 claims took about 3 minutes in testing). The UI verifies one claim at a time for the same reason. For faster runs,
use a Groq plan or model with a higher tokens-per-minute limit and set `GROQ_MODEL` accordingly.

### Corrections: what is right instead

For an INACCURATE or FALSE claim the verdict also carries `original_value`, `corrected_value`, `unit`, `reference_period`, `corrected_claim`, `correction_explanation` and `correction_status`.

- For claims that state a figure, the search step runs a second query for the authoritative figure itself (without the claim's number), so a wrong claim can still be corrected. Both result sets are merged and ranked, with government, institutional and research sources first.
- The AI may only take the correct figure from the numbered evidence. The backend then checks that the figure really appears (compared by value, so "1.43 billion" matches "1,428,627,663"; years must match exactly) in a source the AI cited. If it does not, the correction is discarded and `correction_status` is `not_confirmed`; the verdict itself stays. A confirmed correction is `confirmed`; claims that are not INACCURATE/FALSE are `not_applicable`.
- Every cited source carries the evidence `snippet` as collected from the page, never text written by the AI.
- Corrections are stored with the verdict in Neon and appear in the dashboard and the PDF report. Results are not deterministic: web search results and AI output vary between runs, so a correction may be found in one run and not another.

## Database (Neon PostgreSQL)

Neon PostgreSQL is the **only** persistent storage: documents, claims, evidence, verdicts, report metadata, processing
jobs **and the PDF files themselves** (uploaded PDFs and generated reports, in the `file_objects` table). Nothing is written to
the server's disk, so results and files survive backend restarts and redeploys. See [File storage](#file-storage) for how it
works and its limits.

### Neon setup

1. Create a project in the [Neon console](https://console.neon.tech) (any region).
2. Click **Connect** and copy the **pooled** connection string (the host contains `-pooler`).
3. Put it in `backend/.env` (git-ignored; never in `.env.example`, `.env.local` or any `NEXT_PUBLIC_*` variable):

```
DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require
# Optional: the same URL without "-pooler" in the host, used only for migrations
DATABASE_DIRECT_URL=postgresql://USER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/neondb?sslmode=require
```

The app uses the pooled connection (many short connections). Migrations use the direct one when
`DATABASE_DIRECT_URL` is set, because PgBouncer's transaction pooling does not suit schema changes. Restart the backend
after editing `.env`. Neon may take a few seconds to wake an idle database, so the first request after a pause can be slow.

### Migrations (Alembic)

The app never changes the schema by itself. Run these from `backend/`:

```powershell
.\.venv\Scripts\alembic upgrade head                              # apply all migrations
.\.venv\Scripts\alembic current                                   # which revision the database is at
.\.venv\Scripts\alembic history                                   # list migrations
.\.venv\Scripts\alembic check                                     # fail if the models and the migrations disagree
.\.venv\Scripts\alembic revision --autogenerate -m "what changed" # create a new migration after editing app/db/models.py
.\.venv\Scripts\alembic downgrade -1                              # undo the last migration (destroys data in dropped tables)
```

Always read a generated migration before applying it. `GET /api/health` reports `schema: "current"`, `"outdated"` or
`"not_migrated"`.

### Schema

| Table | Holds | Key columns |
| --- | --- | --- |
| `documents` | One row per upload | `id` (uuid = the `file_id`), `filename`, `file_size`, `total_pages`, `extraction_status`, `processing_status`, `storage_key` (logical key of the PDF, set once it is saved), `access_token_hash` (SHA-256 of the owner's token), `created_at` |
| `claims` | Claims extracted by Groq | `document_id` -> documents, `claim_key` (`claim_001`), `original_claim`, `normalized_claim`, `category`, `value`, `unit`, `time_period`, `context`, `page_number`; plus the claim's search state |
| `evidence` | Tavily sources | `claim_id` -> claims, `source_title`, `source_url`, `source_domain`, `content`, `published_date`, `relevance_score`, `source_type` |
| `verifications` | One verdict per claim | `claim_id` -> claims (unique), `verification_status`, `explanation`, `corrected_claim`, `confidence_score`, `evidence_summary`, fingerprints, full result in `details` |
| `reports` | Generated PDF reports | `document_id` -> documents, `filename`, `status`, `storage_key`, `file_size`, `created_at` |
| `file_objects` | Every stored PDF | `document_id` -> documents, `file_type` (`original_pdf` / `generated_report`), `filename`, `mime_type`, `file_size`, `file_content` (**BYTEA**), `checksum` (SHA-256), `created_at` |
| `processing_jobs` | Each processing step | `document_id` -> documents, `job_type`, `status` (`running`/`completed`/`failed`), `error_message`, `created_at`, `updated_at` |

Relationships: a document has many claims, reports, files and jobs; a claim has many evidence rows and at most one verification.
All child tables use `ON DELETE CASCADE`, so deleting a document (`DELETE /api/files/{id}`) removes only its own data.
Extracting claims again replaces that document's claims, which discards its old evidence and verdicts (they no longer
match). `processing_status` moves `uploaded` -> `claims_extracted` -> `evidence_collected` -> `verified` -> `report_generated`.
Job error messages hold only error codes and our own messages, never document text. Status columns have `CHECK`
constraints, so invalid values are rejected by the database.

The services still pass the same JSON shapes as before; `app/repository.py` maps them to these tables, so the Groq, Tavily
and report logic is unchanged.

### File storage

PDFs live in the `file_objects` table (PostgreSQL `BYTEA`), next to the rest of the data. There is no bucket, no extra
service and no extra credentials, and nothing is written to disk. The logical keys (`documents/<file_id>.pdf`,
`reports/<report_id>.pdf`) and every file id and API route are unchanged.

| What | How |
| --- | --- |
| Upload | The PDF is read into memory with the size limit checked **while reading** (`MAX_UPLOAD_MB`, default and maximum **20 MB**), validated (`.pdf` name, `%PDF-` header, not empty), then the document row **and** its file row are saved in **one transaction**: both exist or neither does. The stored size is read back before the transaction commits. |
| Integrity | A SHA-256 checksum is computed before saving and **verified every time the file is read**. A file that fails is never returned (`500 storage_corrupt`). |
| No duplicates | The database refuses a second original PDF per document and a second identical file (same checksum) of the same type for a document; a re-generated identical report is not stored again. |
| Reading | Only through the API after the access-token check: `GET /api/files/{id}` (the original PDF), `GET /api/report/{id}` (builds a new report and saves a copy), `GET /api/reports/{id}/saved` and `.../saved/{report_id}` (earlier reports). PDF bytes are never part of a JSON response, are not loaded when files are merely listed or counted, and are never logged. |
| Text extraction | PyMuPDF opens the PDF straight from the bytes in memory. |
| Reports | A generated report and its metadata are saved in one transaction. If saving the copy fails, the download still works and the failure is logged by type only. |
| Deleting | Deleting a document (by hand or by retention) deletes its files in the same transaction (`ON DELETE CASCADE`), so there are no orphaned files and no cleanup job. |
| Failures | Database outages are `503 database_unavailable`; an integrity failure is `500 storage_corrupt`; a missing file is a clear `404`. Internal details are logged by type only. |

**Limits of storing files in the database (read before relying on it)**

- **Capacity.** Neon's free plan includes about 0.5 GB of storage for *everything*. Twenty 20 MB PDFs fill 400 MB. Retention
  (`DOCUMENT_RETENTION_DAYS`, default 30) is what keeps it small; `GET /api/health` shows `storage.stored_files` and
  `storage.stored_megabytes` so you can watch it. A paid plan or object storage is the answer if usage grows.
- **Speed.** Every upload and download passes through the backend and the database. Measured from the development machine
  against Neon: a 12 MB PDF took about 14 s to upload, 4 s to extract and 3 s to download; a normal 100 KB PDF is instant.
- **Memory.** A file is held in memory while it is uploaded or read (at most 20 MB), so keep the number of parallel uploads small
  (the per-IP rate limit helps).
- **Backups.** Files are only as safe as your Neon backups and point-in-time restore window; there is no second copy.
- **Not suited to many users or large files.** It is right for a small assignment project, not a high-traffic service.
- **Neon's pooler.** Large rows go through Neon's pooled connection; if you ever see timeouts on very large files, use the direct
  connection string for the backend.

**Moving old local files into the database.** Earlier versions kept files under `backend/storage/`. If any are left,
`.\.venv\Scripts\python scripts\migrate_local_files.py` copies them into `file_objects`, **reads each copy back and checks its
checksum**, and changes nothing else. It never deletes a local file unless you add `--delete-verified-local`, and then only the
ones just verified; files with no matching document or report are reported and left alone. (There were none to migrate on this
project's Neon database.)

### Retention

| Setting | Default | Meaning |
| --- | --- | --- |
| `DOCUMENT_RETENTION_DAYS` | **30** | A document, its stored PDFs, its reports and all its results are deleted this many days after upload. `0` keeps everything. |
| `RETENTION_SWEEP_MINUTES` | 60 | How often the running backend looks for expired documents (it also runs at startup). |
| `ACTIVE_JOB_MINUTES` | 30 | A job still `running` this recently protects its document from cleanup; a job stuck longer (for example after a restart) does not. |

A document and its files are removed together in one transaction, so the database cannot end up with a file whose document is
gone or the other way round. Deleting by hand (`DELETE /api/files/{id}`) does the same. With files in the database, retention is
also what bounds how much storage the project uses.

### Database and security tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q                          # uses throw-away SQLite, never Neon
$env:RUN_NEON_TESTS="1"; .\.venv\Scripts\python -m pytest tests/test_neon_live.py -v   # live Neon checks (creates and deletes its own rows)
```

`tests/test_db.py` covers the schema, saving and reloading every kind of record, relationships, cascade deletes,
rollback, job tracking, report metadata, retention, the health check, and
failure handling (unreachable or unconfigured database, no credentials in responses). `tests/test_neon_live.py` runs the
same flows against the real database. No Groq or Tavily credits are used.

`tests/test_security.py` (access control for every document route: no token, malformed, wrong, another document's token, unknown
document; unauthorised deletion; tokens stored only as hashes and never in responses or logs; rate limits; CORS; security
headers; safe error messages; upload validation; the Groq/Tavily endpoints are never reached by a rejected request),
`tests/test_storage.py` (PDFs in the database: upload and retrieval byte-for-byte, extraction from the stored PDF, checksum
verification and tampering, atomic saves, size and type limits, database constraints, generated and saved reports, missing
files, deletion with its files, retention, persistence after a simulated restart, the local-file migration script) and `tests/test_production.py` (`production_ready` is false for
each missing requirement and true only when all are met; no secrets in `/api/health`). The shared test client attaches the right
token automatically (`tests/conftest.py`) so the older tests are unchanged; the security tests switch that off.
Frontend: `tests/access-token.test.ts` (token storage, header on every request, never in URLs, kept out of UI state).
All storage and security tests run without network access.

## Security model

**There are no user accounts.** Ownership is a **secret access token per document**:

1. `POST /api/upload` returns `access_token` (256 random bits, `secrets.token_urlsafe(32)`) **once**. The database stores only
   its SHA-256 hash (`documents.access_token_hash`), so the token cannot be recovered from the database. SHA-256 is right
   for a high-entropy random token (it is not a password).
2. Every request about that document must send `Authorization: Bearer <token>`: extraction, claim extraction, search,
   verification, the dashboard report, the AI summary, PDF download, saved reports and deletion. The token is compared in
   constant time and is never accepted in a URL (URLs end up in logs and history) and never logged. Files are served only by the API after this check.
3. Responses: `401 missing_token` (no or malformed token), `403 invalid_token` (a token that is not this document's, including
   another document's token), `404 file_not_found` (no such document). Requests are checked **before** any Groq, Tavily or storage
   work, so they cannot be used to spend credits.
4. Documents created before tokens existed have no hash, so nobody can open them (they are removed by retention).

**In the browser** (`src/lib/accessTokens.ts`): the token is kept in `localStorage` under the document id (the 20 most recent
documents) and sent only in the `Authorization` header. It is not kept in React state, URLs or logs. It is in `localStorage`
rather than `sessionStorage` so results can be reopened later; the cost is that a script running on the page could read it,
which is why the site sends a strict Content-Security-Policy (no third-party scripts, no framing) and `Referrer-Policy:
no-referrer`. Consequences: the token lives in that browser only, so a `/results?file=...` link does not work for anyone
else, and **clearing browser data loses access** to the document (upload it again). Add real accounts if you need sharing
or recovery.

**Other protections**

| Area | What is in place |
| --- | --- |
| CORS | Only the origins in `CORS_ORIGINS` (never `*`); methods `GET/POST/DELETE`; headers `Authorization`, `Content-Type`; no cookies/credentials. Rate-limit and error responses carry CORS headers too. |
| Rate limiting | Per client IP per minute: uploads 20, claim extraction + AI summary 10, search 120, verification 60, everything else 300 (`RATE_LIMIT_*`). `429 rate_limited` with `Retry-After`. Failed-auth requests count. The client IP comes from the socket, or from `X-Forwarded-For` only when `TRUSTED_PROXY_COUNT` says how many proxies you run (forged values cannot dodge the limit). The counters are **in this process's memory**, so with several workers the limit is per worker. |
| Credit protection | Groq/Tavily endpoints need the token and the rate limits above; a document can run claim extraction at most `MAX_CLAIM_EXTRACTIONS_PER_HOUR` (10) times an hour (`429 extraction_limit_reached`); searches per document are capped (`MAX_SEARCH_CLAIMS`); documents are capped at `CLAIM_MAX_CHUNKS` sections and `MAX_PDF_PAGES` (300) pages. |
| Uploads | `.pdf` name, `%PDF-` header, non-empty, size limit enforced while streaming, user filenames never used as paths, scanned PDFs reported, page limit. |
| Timeouts | Groq (`GROQ_TIMEOUT_SECONDS`), Tavily (`TAVILY_TIMEOUT_SECONDS`), database connect/pool wait (`DB_CONNECT_TIMEOUT_SECONDS`). |
| Errors | Stable `{code, message}` bodies. Validation errors name the field but never echo the submitted value; unexpected errors are a generic `500 internal_error` (details are logged by type only, never document text). Database and storage outages are `503` without hostnames or credentials. |
| Headers | API: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'`, `Cache-Control: no-store`, `Permissions-Policy`, and `Strict-Transport-Security` over https / in production. Site (`next.config.ts`): CSP limiting scripts, styles, images and `connect-src` to this site and the API, plus the same headers and HSTS. `/docs` is disabled when `APP_ENV=production`. |
| Prompt injection | PDF text, claims and web snippets are always passed to Groq as clearly delimited **untrusted data** inside the user message; the system prompts tell the model to ignore instructions in them, closing tags inside the data are escaped, claims must be verbatim substrings of the PDF, citations must be numbers we sent, and verdicts pass deterministic safety rules (for example FALSE needs authoritative contradicting evidence). A hostile PDF or web page can therefore not change the rules, only (at worst) produce a claim or snippet that is then judged on its evidence. This is mitigation, not a guarantee: always read verdicts critically. |
| Secrets | Keys and URLs live only in `backend/.env` (git-ignored), never in the frontend or `NEXT_PUBLIC_*`. `.env.example` has blanks. Health and error responses never include credentials or connection details. |

**Database review (Neon):** all queries go through SQLAlchemy with bound parameters (the only raw SQL is the constant
`SELECT 1` / `SELECT version_num` health queries), so there is no string-built SQL. Sessions are short units of work that
commit on success, roll back on any error and always release the connection; the pool uses `pool_pre_ping`, recycling and a
wait timeout; Psycopg runs with server-side prepared statements off because Neon's pooler shares connections. Foreign keys
use `ON DELETE CASCADE`, status columns have `CHECK` constraints, and every document query is reached only after the
ownership check. Migrations are explicit (`alembic upgrade head`), never run at startup, and each is reviewed before applying
(`0002` only adds one nullable column). Not set: a per-statement timeout (Neon's pooler does not accept session options);
use Neon's role/compute settings if you want one.

**Known limitations:** no accounts, sharing or token recovery; the token is readable by script injected into the page (the CSP
is the mitigation); rate limits are per process; PyMuPDF parses untrusted PDFs in the API process, so run the backend as an
unprivileged user in a container and keep PyMuPDF updated; there is no malware scanning of uploads.

## Production readiness

`GET /api/health` returns `status` (`ok`/`degraded`, 503 when degraded), `backend`, `database`, `schema` (`current`,
`outdated`, `not_migrated`), `storage` (`backend: database`, reachable, private, files stored and megabytes used), `environment`, `production_ready`,
`checks` and `blockers`. **`production_ready` is `true` only when every one of these is true right now:**

| Check | Needs |
| --- | --- |
| `environment` | `APP_ENV=production` |
| `database` / `schema` | Neon reachable and `alembic upgrade head` applied |
| `file_storage` | The `file_objects` table can be read (checked live, cached 60 s). Needs no external service |
| `document_access_control` | Always on (access tokens) |
| `rate_limiting` | `RATE_LIMIT_ENABLED` not switched off |
| `cors` | `CORS_ORIGINS` contains only `https://` origins and no `*` |
| `retention` | `DOCUMENT_RETENTION_DAYS` above 0 |
| `ai_and_search_keys` | `GROQ_API_KEY` and `TAVILY_API_KEY` set |

Anything missing is listed in `blockers`. The endpoint never shows credentials or connection details. Passing these checks does not replace HTTPS in front of both
servers and the manual steps below.

**Manual steps before deploying** (on Render, `render.yaml` and the [Deploying on Render](#deploying-on-render) guide cover these)

1. Set `APP_ENV=production`, `CORS_ORIGINS=https://your-frontend-domain`, `TRUSTED_PROXY_COUNT` (number of proxies you run), and
   `NEXT_PUBLIC_API_URL=https://your-api-domain` for the frontend build (the CSP and CORS use these).
2. Run `alembic upgrade head` against Neon, then check `/api/health`: `production_ready` must be `true` and `blockers` empty.
3. Serve both over HTTPS. Run the API as an unprivileged user, ideally one container per worker or a shared rate-limit store.
4. **Rotate credentials that may have been exposed:** the Groq key (a key was once pasted into `.env.example`), and, as
   routine hygiene before going live, the Neon password and the Tavily key. Create new ones, update `backend/.env`, restart.
5. Choose `DOCUMENT_RETENTION_DAYS` with Neon's storage allowance in mind (see the file storage limits), and check your Neon
   plan's backup/restore window, because the database is now the only copy of the PDFs.

## Deploying on Render

Everything runs on **Render** (frontend and backend as two web services) plus your existing **Neon** database. There is no
Vercel, no Cloudflare R2 and no S3: PDFs are stored in Neon. `render.yaml` at the repository root is a Render **Blueprint**
that defines both services, so you create them together in one step.

| Piece | Where | Details |
| --- | --- | --- |
| Frontend (Next.js) | Render **Node** web service `truthlayer-ai` | repo root; build `npm ci --include=dev && npm run build`; start `npm run start -- -H 0.0.0.0 -p $PORT`; health check `/` |
| Backend (FastAPI) | Render **Python** web service `truthlayer-ai-api` | `rootDir: backend`; build `pip install -r requirements.txt && alembic upgrade head`; start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; health check `/healthz` |
| Database + PDFs | Neon (existing project) | pooled URL for the app, direct URL for migrations |
| AI / search | Groq / Tavily (existing) | keys only on the backend |

Both services use the **free** plan (a free service sleeps after 15 minutes without traffic and needs about a minute to wake
up; fine for an assignment). The services are placed in the **Singapore** region, next to the Neon project in
`ap-southeast-1`.

### Before you start

1. **Rotate your credentials** (recommended): a Groq key was once pasted into a file, and the Neon password and Tavily key have
   been handled in tools during development. Create new ones (Groq console, Tavily dashboard, Neon > Roles > reset password),
   and update your local `backend/.env`.
2. Have these four secrets ready (never put them in a file you commit):
   - **Neon pooled connection string** (`DATABASE_URL`): Neon console > Connect > *Pooled connection* (host contains `-pooler`).
   - **Neon direct connection string** (`DATABASE_DIRECT_URL`): the same string without `-pooler` in the host.
   - **Groq API key** (`GROQ_API_KEY`) and **Tavily API key** (`TAVILY_API_KEY`).
3. Make sure the repository is on **GitHub** (below).

### 1. Put the code on GitHub (private)

The project is not under a remote yet. Create an empty **private** repository on GitHub (do not add a README or licence), then
from the project folder:

```powershell
git status                                   # review what will be added: no .env, no node_modules, no .venv
git add -A
git status                                   # confirm again: backend/.env and .env.local must NOT be listed
git commit -m "TruthLayer AI"
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

`.gitignore` already excludes `.env*` (except the `.env.example` templates), `backend/.env`, `backend/.venv`, `node_modules`,
`.next`, `backend/storage`, screenshots and logs. Keep the repository private unless you decide otherwise: the code contains no
secrets, but there is no need to publish it.

### 2. Create both services from the Blueprint

1. In the [Render Dashboard](https://dashboard.render.com): **New +** > **Blueprint**.
2. Connect your GitHub account and choose the repository and the `main` branch. Render reads `render.yaml` and lists two
   services: `truthlayer-ai-api` and `truthlayer-ai`.
3. Render asks for the values marked `sync: false` (they are not stored in the repository). Enter:

   | Service | Variable | Value |
   | --- | --- | --- |
   | `truthlayer-ai-api` | `DATABASE_URL` | the Neon **pooled** string |
   | `truthlayer-ai-api` | `DATABASE_DIRECT_URL` | the Neon **direct** string |
   | `truthlayer-ai-api` | `GROQ_API_KEY` | your Groq key |
   | `truthlayer-ai-api` | `TAVILY_API_KEY` | your Tavily key |
   | `truthlayer-ai-api` | `CORS_ORIGINS` | `https://truthlayer-ai.onrender.com` (the frontend's address) |
   | `truthlayer-ai` | `NEXT_PUBLIC_API_URL` | `https://truthlayer-ai-api.onrender.com` (the backend's address) |

   These two addresses are the ones Render gives the services *if the names are free*. Render service names are global, so if
   `truthlayer-ai` or `truthlayer-ai-api` is taken, Render adds a random suffix. In that case rename the services in
   `render.yaml` to something unique **before** creating the Blueprint, or fix the two values afterwards (step 3).
4. Click **Apply**. Both services build. The backend's build ends with `alembic upgrade head`, which applies the database
   migrations through the **direct** Neon connection **before** the new version starts (a failed migration fails the deploy and the
   old version keeps running).

### 3. Check the addresses and fix them if needed

Open each service and read its URL under the service name. They must be exactly:

- backend `CORS_ORIGINS` = the **frontend's** `https://...onrender.com` URL (no trailing slash, never `*`)
- frontend `NEXT_PUBLIC_API_URL` = the **backend's** `https://...onrender.com` URL (no trailing slash)

If either differs: **Environment** tab > edit the value > save. For the backend Render redeploys by itself. For the frontend you
must rebuild, because `NEXT_PUBLIC_*` values are compiled into the browser bundle: **Manual Deploy > Clear build cache & deploy**.

### 4. Verify the deployment

1. Open `https://<backend>/healthz` -> `{"status":"ok"}` (this is the probe Render uses; it does not touch the database).
2. Open `https://<backend>/api/health`. You want `"status":"ok"`, `"production_ready": true` and `"blockers": []`. If not, `blockers`
   says exactly what is missing (for example a `cors` blocker means `CORS_ORIGINS` is not an `https://` origin). The check never
   exposes secrets and cannot be forced: `production_ready` is computed from the real state.
3. Open the frontend URL and run the full flow with a **small PDF** (a page or two, to save API credits): upload, extract text,
   extract claims (Groq), search the web (Tavily), verify, view the dashboard, download the PDF report.
4. Reload the page: the results are still there (they are in Neon, and the access token is in your browser).
5. Restart check: backend service > **Manual Deploy > Restart service** (or just wait for it to sleep and wake), then reload the
   results and download the original PDF again: everything is still there.
6. Security check: open the API in another browser (or a private window) without the token:
   `https://<backend>/api/reports/<file_id>` -> `401`; with a wrong token -> `403`.
7. In the browser's developer tools, check that the page makes requests only to the frontend and backend addresses, and search the
   page source for your keys: they are never there (only the public backend URL is).

### Environment variables

**Backend (`truthlayer-ai-api`)**: set in `render.yaml` or the Dashboard. Everything not listed uses the default shown in
[Configuration](#configuration).

| Variable | Required | Value on Render |
| --- | --- | --- |
| `DATABASE_URL` | yes, secret | Neon **pooled** string (used by the app) |
| `DATABASE_DIRECT_URL` | yes, secret | Neon **direct** string (used only by `alembic upgrade head`) |
| `GROQ_API_KEY` | yes, secret | your Groq key |
| `TAVILY_API_KEY` | yes, secret | your Tavily key |
| `CORS_ORIGINS` | yes | the frontend's exact `https://` origin |
| `APP_ENV` | yes | `production` (no `/docs`, HSTS, and required for `production_ready`) |
| `PYTHON_VERSION` | yes | `3.13.5` |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` |
| `TAVILY_SEARCH_DEPTH` | no | `basic` (1 credit per search) |
| `DOCUMENT_RETENTION_DAYS` | no | `30` (documents, PDFs and results are deleted after this; keep Neon's storage allowance in mind) |
| `RATE_LIMIT_ENABLED` | no | `true` |
| `TRUSTED_PROXY_COUNT` | no | `1` (Render's proxy is in front of the API) |
| `CLIENT_IP_HEADER` | no | `CF-Connecting-IP` (Cloudflare overwrites it, so it identifies the real visitor for rate limits; ignored if absent) |
| `MAX_UPLOAD_MB` | no | `20` (the maximum: PDFs live in the database) |

Other optional settings (pool size, per-endpoint rate limits, page limit, extraction cap, retention timing, Groq/Tavily timeouts)
are in `backend/.env.example` and [Configuration](#configuration). `PORT` is set by Render; do not set it.

**Frontend (`truthlayer-ai`)**

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | the backend's public `https://` URL (public by design; compiled into the bundle at build time) |
| `NODE_VERSION` | `24.22.1` |
| `NEXT_TELEMETRY_DISABLED` | `1` |

Never put a secret in a `NEXT_PUBLIC_*` variable: everything with that prefix is sent to every visitor's browser.

### How the deployment behaves

- **Migrations** run in the backend's build step with the direct Neon connection, so the schema is current before the new
  version receives traffic. On a paid plan, move the command to `preDeployCommand: alembic upgrade head` (pre-deploy commands are
  not available on the free plan). Running migrations is a deliberate deploy step; the app itself never changes the schema.
- **Health checks.** Render probes `/healthz` (backend) and `/` (frontend). `/healthz` deliberately does not query the database:
  Render probes every few seconds, and that would keep Neon awake and use up its free compute hours. Use `/api/health` (or a
  monitor that calls it occasionally) for the real database/storage/readiness check.
- **Networking.** The backend listens on `0.0.0.0:$PORT`; Render terminates HTTPS in front of both services and the app sends
  HSTS. CORS allows exactly the frontend origin, so a request from any other website is refused by the browser.
- **Cold starts.** After 15 minutes idle a free service sleeps; the first request wakes it (about a minute). Neon also scales to
  zero, so the very first database query after a quiet period can take a few extra seconds. Data is never lost: everything is in Neon.
- **Retention** runs inside the backend (at start-up and hourly while it is awake).
- **Restarts and redeploys** lose nothing: the server keeps no files and no state; PDFs, reports, results and access-token hashes are
  all in Neon. A visitor's access token lives in their browser, so clearing browser data loses access to that document.
- **Rate limits** are counted in the backend process (one worker). They identify visitors by `CF-Connecting-IP`, falling back to the
  last `X-Forwarded-For` entry (`TRUSTED_PROXY_COUNT=1`). If you ever see all visitors sharing one limit, the header is not arriving:
  check `CLIENT_IP_HEADER` and Render's current proxy headers.

### Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Browser console: CORS error / "blocked by CORS policy" | Backend `CORS_ORIGINS` is not exactly the frontend origin (scheme, host, no trailing slash). Fix it and let the backend redeploy. |
| Requests go to `localhost:8000` | The frontend was built without `NEXT_PUBLIC_API_URL`. Set it, then **Clear build cache & deploy**. |
| Upload/extract fails with `503 database_unavailable` | Neon is waking up (retry) or the `DATABASE_URL` is wrong/expired. Check `/api/health`. |
| `/api/health` shows `schema: not_migrated` or `needs_migration` | The build step did not run migrations. Check the build log for `alembic upgrade head`, and `DATABASE_DIRECT_URL`. |
| Backend build fails at `alembic upgrade head` | `DATABASE_DIRECT_URL` missing or wrong; the previous version keeps serving. Fix the variable and redeploy. |
| `production_ready` is false | Read `blockers` in `/api/health`; each entry names the failing check. |
| Everything is slow after a pause | Free-plan cold start (service and Neon). Wait a minute and retry. |
| `429 rate_limited` while testing | You hit a per-minute limit (see Security model); wait for `Retry-After`. |

### What was verified before deployment, and what was not

Verified locally: the frontend production build; the backend's build step (migrations against the real Neon database) and start
command, run exactly as Render will (no `.env` file, configuration only from environment variables, `0.0.0.0:$PORT`), with
`/api/health` reporting `production_ready: true`; CORS accepting only the HTTPS frontend origin; every backend dependency
resolving to a prebuilt Linux wheel for Python 3.13; no secret in the repository, the git history or the built frontend. **Not
yet verified, because it needs the real services:** the Render build itself, Render's HTTPS and proxy headers, the deployed
frontend talking to the deployed backend, and the live Groq and Tavily calls from Render. The checklist in step 4 covers these.

## Results dashboard (`/results`)

Open it from **Open full results dashboard** on the Dashboard page (after verifying), or go to `/results`: it reopens
the last document processed in this browser. `/results?file=<file_id>` opens a specific one.

- **Real data only.** The page loads `GET /api/reports/{file_id}`, which merges the saved claims, collected evidence
  and verdicts. Nothing is hardcoded. Counts on the cards, in the charts and in the table are all derived from the
  same list of claims, so they always agree (tested). Demo data lives only on `/results/demo`, labeled **DEMO DATA**.
- **Overview:** document name, total claims, and four clickable status cards (green Verified, orange Inaccurate,
  red False, grey Unverified). Clicking a card filters the table; click again or use **Clear filters**. Claims without a
  current verdict show as "Not verified yet" with a link to filter them.
- **Charts** (plain SVG, no chart library): status distribution donut, overall breakdown bar, claims by category.
  Hover for exact counts; the legends double as a data table.
- **Document summary:** a built-in sentence computed from the counts, an **AI-written narrative** of the same
  results (generated once, cached, and rejected if it mentions any number not in the data), and a "Needs further
  investigation" list (unverified claims, forecasts/examples, thin-evidence verdicts, claims not yet verified). It never
  adds new factual conclusions; if the AI fails, the built-in summary remains.
- **Claims table:** search, status filter, category filter, sorting (page, confidence, status, category, supporting
  sources), pagination (10 per page), and a **View** action. Columns that do not fit move under the claim text on
  smaller screens.
- **Claim details** (side panel on wide screens, full-screen sheet on phones; Esc closes): original claim, verdict,
  AI explanation, corrected claim, confidence, evidence summary, **supporting** (green) and **contradicting** (red)
  sources with clickable links and publication dates, the PDF page, and other collected sources the verdict did not cite.
- **States:** loading skeletons, empty states (no document, no claims, no matches), error states with retry, an
  "expired report" state, and a banner when claims are not verified yet.

**Persistence:** results are saved in Neon and survive restarts. A document (with its PDFs and results) is kept for
`DOCUMENT_RETENTION_DAYS` (default 30); after that `/results` says the report is no longer available. Reopening needs the
access token stored in the browser that uploaded the document (see [Security model](#security-model)).

## PDF report

**Download PDF Report** (top of `/results`) downloads a professional A4 report built from the saved results.

- **Enabled** once every claim has a current verdict. While any claim is not verified yet (or its evidence changed
  after it was verified) the button is disabled and says how many claims remain. The backend enforces the same rule
  (HTTP 409 `verification_incomplete`). A document with no claims still produces a short report saying so.
- **Contents:** (A) cover page with branding, file name, generation time and claim count; (B) executive summary with
  totals, whole-number percentages that always add up to 100%, the built-in summary, the AI-written summary if one was
  already generated, and the follow-up list; (C) verification overview with a status bar, a count/percentage table and a
  per-category breakdown; (D) a separate section per claim with ID, original text, PDF page, category, colored verdict
  badge, confidence, AI explanation, corrected information, evidence summary and supporting and contradicting sources with
  dates; (E) a sources table (claim ID, role, title, date, clickable URL); (F) limitations and the required disclaimer.
  Page numbers ("Page 3 of 12") and branding appear on every page after the cover.
- **Real data only.** The PDF is rendered by `GET /api/report/{file_id}` with ReportLab from the same saved claims,
  evidence and verdicts as the dashboard (`report.py`). **It never calls Groq or Tavily**, so it costs nothing and is
  repeatable. It is generated in memory and streamed, so no temporary file is written or left behind.
- **Safe rendering.** Text from the uploaded PDF and the web is untrusted: control characters are removed, markup is
  escaped (so `<b>` or `<script>` in a source title is printed literally), only `http(s)` URLs become links, and very long
  words and URLs wrap instead of overflowing. Text is selectable and links are clickable.
- **Unicode.** Noto Sans (SIL Open Font License, `backend/app/assets/fonts/`, license in `OFL.txt`) is embedded, so
  ₹ € £ ¥ % curly quotes, dashes and accented Latin, Greek and Cyrillic letters render correctly. A few symbols the font lacks
  are replaced by ASCII (≈ becomes ~, → becomes ->). Scripts the font does not cover (for example Devanagari or CJK
  text) print as `?` rather than as empty boxes; add a font to `assets/fonts/` to extend coverage.
- **Availability.** Reports are built from the results saved in Neon, so they survive restarts and redeploys and are available until
  the document's retention period ends (`DOCUMENT_RETENTION_DAYS`, default 30). Each generated PDF is also saved in the database.

## Configuration

| File | Variable | Purpose |
| --- | --- | --- |
| `.env.local` | `NEXT_PUBLIC_API_URL` | Backend URL used by the browser. Public: never put secrets here. |
| `backend/.env` | `MAX_UPLOAD_MB` | Max upload size in MB (default and maximum 20: PDFs are stored in the database) |
| `backend/.env` | `CORS_ORIGINS` | Allowed frontend origins (default `http://localhost:3000`) |
| `backend/.env` | `DATABASE_URL` | Neon **pooled** connection string (server-side only, required) |
| `backend/.env` | `DATABASE_DIRECT_URL` | Neon direct connection, used only by Alembic (optional) |
| `backend/.env` | `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_CONNECT_TIMEOUT_SECONDS` | Connection pool (5 / 5) and connect timeout (15) |
| `backend/.env` | `APP_ENV` | `development` (default) or `production` (no `/docs`, HSTS, needed for `production_ready`) |
| `backend/.env` | `DOCUMENT_RETENTION_DAYS` | Delete documents older than this many days (default 30, 0 = keep) |
| `backend/.env` | `RETENTION_SWEEP_MINUTES` / `ACTIVE_JOB_MINUTES` | Cleanup interval (60) / how long a running job protects its document (30) |
| `backend/.env` | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_{UPLOAD,EXTRACT,SEARCH,VERIFY,DEFAULT}_PER_MINUTE` | Per-IP request limits (20 / 10 / 120 / 60 / 300) |
| `backend/.env` | `TRUSTED_PROXY_COUNT` | Reverse proxies in front of the API (default 0) |
| `backend/.env` | `CLIENT_IP_HEADER` | Header the proxy overwrites with the real client IP, e.g. `CF-Connecting-IP` on Render (default none) |
| `backend/.env` | `MAX_CLAIM_EXTRACTIONS_PER_HOUR` / `MAX_PDF_PAGES` | Per-document Groq extraction cap (10) / page limit (300) |
| `backend/.env` | `GROQ_API_KEY` | Groq key (server-side only, required for claims) |
| `backend/.env` | `GROQ_MODEL` | Groq model (default `openai/gpt-oss-120b`) |
| `backend/.env` | `GROQ_TIMEOUT_SECONDS` | Per-request timeout (default 60) |
| `backend/.env` | `CLAIM_CHUNK_CHARS` / `CLAIM_MAX_CHUNKS` | Chunk size (default 6000) / max chunks per document (default 40) |
| `backend/.env` | `TAVILY_API_KEY` | Tavily key (server-side only, required for web search) |
| `backend/.env` | `TAVILY_SEARCH_DEPTH` | `basic` (default, 1 credit) or `advanced` (2 credits) |
| `backend/.env` | `TAVILY_MAX_RESULTS` / `TAVILY_FETCH_RESULTS` | Sources kept per claim (5) / results requested per query (8) |
| `backend/.env` | `TAVILY_TIMEOUT_SECONDS` | Per-search timeout (default 20) |
| `backend/.env` | `MAX_SEARCH_CLAIMS` | Max claims searched per document (default 50) |

## API

Every route that takes a `file_id` also needs `Authorization: Bearer <access_token>` (the token returned by `POST /api/upload`); see [Security model](#security-model).

| Method | Route | Description |
| --- | --- | --- |
| GET | `/healthz` | Liveness only: `{"status":"ok"}`, no database access (used by Render's health probe). |
| GET | `/api/health` | Backend, database and storage status: `status` (`ok`/`degraded`), `database` (`status` `ok`/`unavailable`/`not_configured`/`needs_migration`, `latency_ms`, `schema`), `storage` (`backend`, `production_ready`). Returns 503 when degraded. Never includes credentials. |
| POST | `/api/upload` | Multipart upload (`file`). Returns `file_id`, `filename`, `file_size`, `upload_status` and `access_token` (**shown once**; only its hash is stored). The PDF and the document are saved in one transaction; if either cannot be saved the upload fails. |
| POST | `/api/extract` | Body `{ "file_id": "..." }`. Returns per-page text (`pages[].page_number`, `extracted_text`), `total_pages`, `extraction_status` (`success`, `partial`, `no_text`), `ocr_required`, `empty_pages`. |
| POST | `/api/claims/extract` | Body `{ "file_id": "..." }`. Returns `total_claims` and `claims[]` (`claim_id`, `claim_text`, `normalized_claim`, `category`, `value`, `unit`, `time_period`, `context`, `page_number`, `verification_status: "pending"`), plus `status` (`complete`/`partial`), `warnings`, `model`. |
| POST | `/api/claims/search` | Body `{ "file_id": "...", "claim_ids"?: [...], "refresh"?: false }`. Searches the web for each extracted claim. Returns `total_claims`, `total_sources_found`, `status`, `search_depth`, `warnings` and `claims[]` (`claim_id`, `claim_text`, `search_status`, `search_query`, `query_source`, `sources[]` with `title`, `url`, `content`, `published_date`, `score`, `domain`, `source_type`, `claim_id`; `sources_found`, `cached`, `error`, `verification_status: "pending"`). `claim_ids` limits the search to some claims (the UI uses this for per-claim progress). |
| POST | `/api/claims/verify` | Body `{ "file_id": "...", "claim_ids"?: [...], "refresh"?: false }`. AI fact-checks claims against the saved evidence. Returns `total_claims`, `verified`, `inaccurate`, `false`, `unverified`, `failed`, `status`, `warnings` and `results[]` (`claim_id`, `original_claim`, `pdf_page`, `check_status` `completed`/`failed`, `verification_status` `VERIFIED`/`INACCURATE`/`FALSE`/`UNVERIFIED` or null if failed, `claim_type`, `explanation`, `corrected_claim`, `confidence_score`, `evidence_summary`, `supporting_sources[]` / `contradicting_sources[]` (`title`, `url`, `relevance`, `domain`, `source_type`, `published_date`), `adjustments`, `cached`, `error`). |
| GET | `/api/reports/{file_id}` | Everything the results dashboard needs: `document_name`, `stage` (`claims_extracted`/`evidence_collected`/`verified`), `counts` (`total`, `verified`, `inaccurate`, `false`, `unverified`, `pending`), `categories[]`, `claims[]` (each with its category, `status` incl. `PENDING`, `confidence_score`, `supporting_count`, `contradicting_count`, collected sources and full verdict), `summary` (`text`, `needs_investigation[]`, `narrative`) and `warnings`. A verdict is hidden (`stale: true`, status `PENDING`) if the evidence changed after it was made. 404 if the file expired, 409 if no claims were extracted. |
| POST | `/api/reports/{file_id}/summary` | Adds the AI-written `summary.narrative` (cached; `?refresh=true` rewrites it). Never fails because of the AI: on error it returns the built-in summary with `narrative_error`. |
| GET | `/api/report/{file_id}` | The fact-checking report as a PDF download (`Content-Type: application/pdf`, `Content-Disposition: attachment; filename="truthlayer-fact-check-<name>.pdf"`). Built only from saved results; never calls Groq or Tavily. `400 invalid_file_id`, `404 file_not_found`, `409 claims_not_extracted`, `409 verification_incomplete` (message says how many claims remain), `500 report_generation_failed`. Note the singular `report`: `/api/reports/...` returns the dashboard JSON. |
| GET | `/api/reports/{file_id}/saved` | Previously generated PDF reports of this document (`id`, `filename`, `file_size`, `created_at`, `has_file`). |
| GET | `/api/reports/{file_id}/saved/{report_id}` | Streams a stored report from the database. |
| GET | `/api/files/{file_id}` | The original uploaded PDF, streamed from the database (`attachment`, never JSON). |
| DELETE | `/api/files/{file_id}` | Delete a document with its stored PDF, reports, claims, evidence, verdicts, summary and jobs |

Errors return `{ "detail": { "code", "message" } }`. Access: `missing_token` (401), `invalid_token` (403), `file_not_found` (404). Limits: `rate_limited` (429, with `Retry-After`), `extraction_limit_reached` (429), `too_many_pages` (413). Server: `storage_error` (502, a file could not be saved completely), `storage_corrupt` (500, a stored file failed its checksum), `database_unavailable` (503), `database_not_configured` (503), `database_error` (500), `invalid_request` (422), `internal_error` (500), `report_not_found` (404). Other codes: `invalid_file_type`, `invalid_pdf`, `empty_file`,
`file_too_large` (413), `file_not_found` (404), `corrupted_pdf`, `password_protected`, `empty_pdf`, `no_text` (422),
`document_too_long` (413). Groq errors: `groq_not_configured` (503), `groq_auth_failed` (502), `groq_rate_limited` (429),
`groq_timeout` (504), `groq_unreachable`, `groq_malformed_response`, `groq_error` (502). Search: `claims_not_extracted` (409),
`unknown_claim_id` (400), `tavily_not_configured` (503), `tavily_auth_failed` / `tavily_forbidden` (502),
`tavily_credits_exhausted` (402), `tavily_rate_limited` (429), `tavily_timeout` (504), `tavily_malformed_response`,
`tavily_bad_request`, `tavily_error` (502). Timeouts, rate limits and malformed responses are recorded on the individual
claim (`search_status: "failed"`) instead of failing the whole request. Verification: `evidence_not_collected` (409, no search
was run yet), `evidence_missing` (a claim has no collected evidence), plus the Groq codes above. A claim the AI could not
check comes back with `check_status: "failed"` and no verdict; it is never silently labelled UNVERIFIED.

Security notes: files are stored under random server-generated IDs (user filenames are never used as paths),
the size limit is enforced while streaming, content is checked for a PDF header, and stale temporary working copies are
cleaned up automatically. Scanned/image-only PDFs are detected and reported as needing OCR (OCR is not implemented).

## Dependency audit

Last run (this project): `npm audit` **0 vulnerabilities**, `pip-audit` on the installed backend packages **no known
vulnerabilities**. `boto3` was removed with the S3 backend. Fixes applied: Vitest 3 -> 4.1.12 (patched `@vitest/mocker` and `tinypool`; all tests still pass), an npm
`overrides` entry that makes Next.js use PostCSS >= 8.5.33 (Next 15 pins the vulnerable 8.4.31; the production build and tests
were re-run), and `pytest` 8 -> 9.2 (moved to `requirements-dev.txt`, so production installs contain no test tools). Not done:
a major upgrade to Next 16 or Vitest 5 (breaking; Vitest 5.1.1 failed on this project earlier). Re-run `npm audit` and
`pip-audit -r requirements.txt` regularly. The repository contains no real secrets: the working tree and git history were
scanned for the actual values in `backend/.env` and for key patterns (the only match is a fake test string).

## Tests

```powershell
# Backend (pytest; Groq and Tavily are mocked, no credits used; needs requirements-dev.txt)
cd backend
.\.venv\Scripts\python -m pytest -q

# Frontend (Vitest + Testing Library, API mocked)
cd ..
npm test
```

`tests/` at the project root holds the frontend tests: `report-lib.test.ts` (filtering, search, sorting, pagination,
counts), `dashboard.test.tsx` (statistics, clickable status cards, category filter, search, claim details, supporting vs
contradicting sources, link safety, summary, loading/empty/error states) and `results-page.test.tsx` (which document
`/results` opens). `tests/fixtures.ts` contains fake data used only by the tests. `backend/tests/test_report.py` covers the
report endpoint: counts equal the claim tally, ids and pages are preserved, stale verdicts, categories, the template and AI
summary (including the invented-number guard).

**Responsive/visual check:** `node scripts/screenshot-results.cjs <file_id>` opens `/results` in Microsoft Edge at desktop
(1366px) and phone (390px) widths, fails if there is horizontal overflow or a browser console error, **clicks Download PDF
Report and checks that a real PDF arrives**, and saves screenshots. It needs both servers running and a verified document;
it uses `playwright-core` with the installed Edge, so no browser download is needed.

**PDF report tests:** `backend/tests/test_pdf_report.py` builds a 12-claim document (all four verdicts, 900-character
claims, a 136-character unbroken word, a 300-character URL, ₹/€/£ and CJK text, markup in titles, sources with no title or
date, several pages) through the real verify endpoint with a mocked AI, then opens the generated PDF with PyMuPDF and
checks: counts and percentages (sum to the total and 100%), one section per claim in order with IDs, pages, categories and
verdicts, exact claim text, supporting vs contradicting sources, clickable link targets (exact, including the long URL),
no unsafe links, selectable text and embedded fonts, page numbers on every page, text inside page bounds and non-overlapping,
the required disclaimer, empty reports, invalid/unknown ids, downloads before extraction or verification, stale evidence,
generation failures, and that **no Groq or Tavily function is called** and no file is written while generating. Set
`TRUTHLAYER_SAVE_SAMPLE=path.pdf` when running it to keep the sample report for visual inspection. Frontend tests
(`tests/dashboard.test.tsx`, `tests/download.test.ts`, `tests/demo-page.test.tsx`) cover the button states (enabled, disabled
with a reason, loading, duplicate clicks ignored, errors, retry), the download client and that the demo page has no download.

`tests/test_claims.py` mocks Groq completely, so tests use no network and no API credits. It covers missing/invalid
keys, rate limits, timeouts, partial failures, malformed and repaired AI output, hallucinated claims, wrong page
numbers, duplicates, chunking, oversized requests and prompt-injection handling.
`tests/test_search.py` mocks Tavily (and Groq) the same way: valid/missing/invalid keys, successful and empty searches,
multiple claims, duplicate URLs, source ranking and URL safety, timeouts, rate limits (with retry), credit exhaustion
mid-run, malformed responses, caching and the per-document limit.
`tests/test_verify.py` mocks Groq for the fact-checker: supported, contradicted, outdated, insufficient, conflicting,
prediction, hypothetical and multi-source claims; missing evidence; Groq failures, timeouts and rate limits; invalid and
repaired AI JSON; invented sources; every safety rule; prompt-injection handling; and caching of repeated requests.
`tests/test_api.py` covers upload and extraction: valid, multi-page, partially empty, blank, scanned (image-only), corrupted, truncated,
password-protected, non-PDF, fake-PDF, empty and oversized files, plus path-traversal IDs and deletion.

## Try the claims feature manually

1. Set `GROQ_API_KEY` in `backend/.env`, start both servers (below), open http://localhost:3000/dashboard.
2. Upload a text PDF containing facts (e.g. "Global EV sales grew 35 percent in 2023 to 14 million units."),
   click **Analyze document**, then **Extract Claims with AI**.
3. Check that each claim shows the right value, unit, period and PDF page, with a "Pending verification" badge.
4. Or call the API directly: `curl -X POST localhost:8000/api/claims/extract -H "Content-Type: application/json" -d "{\"file_id\":\"<id from /api/upload>\"}"`

## Try the web search manually

1. Set both keys in `backend/.env`, restart the backend, and extract claims as above.
2. Click **Search Web for Evidence**. A progress bar counts claims as they finish (3 searched at a time).
3. Each claim shows a status (Waiting for search, Searching, Evidence found, No relevant sources, Search failed) and a
   **Show evidence** section with the query, source titles (clickable), domains, type, date and snippet.
4. Check that every claim still says **Pending verification**.
5. Or call it directly: `curl -X POST localhost:8000/api/claims/search -H "Content-Type: application/json" -d "{\"file_id\":\"<id>\"}"` (after extracting claims for that file).
6. Remove `TAVILY_API_KEY` to see the missing-key error, or put in a wrong one to see the invalid-key error.

## Try the fact-checking manually

1. With both keys set, extract claims and click **Search Web for Evidence** as above.
2. Click **Verify All Claims**. A progress bar counts claims as they finish (3 at a time).
3. Each claim now shows a coloured badge (green VERIFIED, orange INACCURATE, red FALSE, grey UNVERIFIED), the AI's
   explanation, corrected information when available, an evidence-strength bar, and **Show evidence** for the
   supporting and contradicting sources (clickable) and the PDF page. The summary cards at the top count each verdict and
   filter the list when clicked.
4. A good test PDF mixes: a true fact ("The Eiffel Tower was completed in 1889."), a myth ("The Great Wall of China is
   visible from the Moon with the naked eye."), a forecast ("India will have 1 billion smartphone users by 2030.") and a
   hypothetical example ("For example, Priya sends Rs 500 by UPI...").
5. Click **Verify again**: nothing is re-sent to Groq (cached) unless the evidence changed.
   Then click **Open full results dashboard** to see the analytics page (`/results`).
6. Or call it directly: `curl -X POST localhost:8000/api/claims/verify -H "Content-Type: application/json" -d "{\"file_id\":\"<id>\"}"`
   (after extracting claims and searching for that file).

Verdicts are AI-assisted and based only on the few web excerpts collected for each claim. Always review the sources.

## Project structure

```
backend/
  app/            main.py (routes), extraction.py, storage.py, schemas.py, config.py,
                  claims.py (chunking, prompting, validation, dedup), llm.py (Groq wrapper), claim_schemas.py,
                  search.py (queries, ranking, caching), tavily_client.py (Tavily wrapper), search_schemas.py,
                  verify.py (AI fact-checker, safety rules, caching), verify_schemas.py,
                  report.py (dashboard data, summary), report_schemas.py,
                  pdf_report.py (ReportLab PDF), assets/fonts/ (Noto Sans + OFL license)
  app/db/         models.py (SQLAlchemy schema), session.py (engine, sessions, health check)
  app/repository.py (database reads/writes), filestore.py (PDFs in Neon, table file_objects), auth.py (access tokens),
  middleware.py (rate limits, secure headers), readiness.py (production_ready)
  scripts/        migrate_local_files.py (copy leftover local files into the database, verified)
  alembic/        migrations (alembic.ini at backend/)
  tests/          pytest suite (pdf_fixture.py = sample verified document for the PDF tests)
  requirements.txt, .env.example
src/
  app/            routes: / , /dashboard , /results (real) , /results/demo (demo data)
  components/     Navbar, Sidebar, Footer, UploadCard, UploadWorkspace, ExtractedTextPreview, ClaimsSection, ClaimCard, EvidencePanel,
                  VerdictPanel, VerificationSummary, ResultsDashboard, ResultsTable, ClaimDetails, DocumentSummary,
                  Charts, StatCard, ClaimTable, StatusBadge, ClaimDetailPanel, EmptyState
  lib/            api.ts (backend client), download.ts (browser download), status.ts, report.ts, demoData.ts
  types/          shared TypeScript types
```

## Roadmap

- Next: deploy on Render with `render.yaml` (see [Deploying on Render](#deploying-on-render)), then run the post-deploy checklist
- Later: user accounts (sharing, token recovery), a shared rate-limit store, OCR for scanned PDFs, more fonts for non-Latin scripts in the PDF
