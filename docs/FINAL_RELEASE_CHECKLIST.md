# Covenant Intelligence — Final Project Audit

**Audit date:** 2026-11-03  
**Scope:** Repository and implementation review for public source submission, followed by live-provider error-path verification on a synthetic agreement. Application error reporting and tests were updated. A new extraction-run record was created in the existing local database; no existing agreement, source PDF, or approved obligation was modified or reset. No ZIP was created and nothing was pushed.

**Final integration addendum (2026-11-03):** CORS is configurable and verified on a non-default Vite port. A synthetic HTTP API workflow completed with persistence using a mock provider. A later real OpenRouter request using only a synthetic agreement reached the provider but returned HTTP 402 for insufficient credits and produced no candidates. PostgreSQL and a true browser UI workflow remain unverified for the reasons below.

## Executive recommendation

**Not cleared for public GitHub submission yet; conditionally suitable for a public source-code review after a clean staging review.** The implementation and documentation are substantial and the deterministic test suites pass. The security scan found no credential-like values, and `.env.example` contains placeholders. However, this workspace has no `.git` directory, so there is no tracked/staged-file inventory to prove what a first commit would contain. The workspace also contains local databases and generated test PDF artifacts that must stay out of any public commit. Review a fresh Git staging area before publishing.

This project is **not production-ready**. It uses seeded development identities, has no production authentication, has no live-provider quality evaluation, and has not been verified against PostgreSQL or Docker in this environment.

## 1. Implemented features across Steps 1–5

| Step | Delivered scope | Audit finding |
| --- | --- | --- |
| 1 — Design | Modular-monolith architecture, domain constraints, data model, extraction contract, API design, development-only identity model. | Documented in architecture/data-model/design documents. |
| 2 — PDF ingestion | Agreement creation, versioned PDF upload, original byte storage, page-by-page PyMuPDF text extraction, page hashes, text viewer endpoints/UI. | Backend PDF workflow tests pass; UI upload/text test passes with mocked HTTP responses. |
| 3 — Extraction | OpenRouter/OpenAI-compatible provider adapter, chunk selection, versioned canonical schema, structured candidates, evidence validation, deterministic definition/reference lookup. | Mock-provider tests pass. No live OpenRouter run was performed. |
| 4 — Finance workflows | Human review/correction, approved register and revisions, quarterly monitoring, amendment proposals, audit history. | API workflow tests pass against an isolated FastAPI test database. Frontend workflow tests use mocked fetch responses. |
| 5 — Submission evaluation/safety | Ten synthetic gold examples, fixture-integrity scorer, role-specific monitoring authorization, amendment removal coverage safeguards and full-document attestation, final evaluation and AI-use documents. | Fixture integrity passed. Real LLM quality remains unmeasured. |

Domain restrictions are reflected in the implementation and docs: no ratio/headroom calculation, ERP integration, automatic approval, binding legal advice, OCR, or private agreement examples are intended.

## 2. Backend architecture and database design

The backend is a FastAPI modular monolith. HTTP routers are split across agreement/document, extraction, and workflow modules. Supporting modules separate document processing, extraction chunking/providers/prompts/validation/persistence, obligations/evidence, human review, monitoring, amendment comparison, and audit. SQLAlchemy is the ORM; Alembic owns schema evolution; Pydantic validates API and extraction payloads. SQLite is used by tests/local development; PostgreSQL is the intended shared system of record.

Principal relationships:

- A workspace owns agreements and memberships; development users receive roles through memberships.
- Agreements have immutable document versions; versions contain page text and hashes and may have extraction runs.
- Runs produce immutable extraction candidates. Each candidate stores the full canonical JSON payload and relational evidence rows.
- Review decisions are separate from candidates. Approval creates an obligation revision containing the full approved payload and relational evidence rows.
- Obligations have revision history and monitoring periods/updates.
- Amendment comparisons contain proposed items and reviewer decisions; each decision is separately persisted.
- Audit events reference workspace, actor, entity, timestamp, action, and allowlisted summary data.

JSON payloads use JSON with a PostgreSQL JSONB variant. Evidence has separate relational rows in the same transaction as candidate/revision persistence. Candidate/revision immutability is guarded by ORM events; audit events are append-only at the ORM layer, not a tamper-proof external ledger.

Migrations present: `0001_initial`, `0002_extraction_metadata_and_role_constraints`, `0003_review_monitoring_amendment_audit`, and `0004_amendment_review_safety`.

## 3. Implemented API endpoints

All application endpoints use `/api/v1`, except `/health`. Authorization resolves `X-Dev-User` to the seeded development workspace and checks workspace membership/role. The header is a development identity switch, not production authentication.

### Health, agreements, and documents

- `GET /health`
- `GET /api/v1/agreements`
- `POST /api/v1/agreements`
- `GET /api/v1/agreements/{agreement_id}`
- `POST /api/v1/agreements/{agreement_id}/versions` (multipart PDF upload)
- `GET /api/v1/agreements/{agreement_id}/versions`
- `GET /api/v1/agreements/{agreement_id}/versions/{version_id}`
- `POST /api/v1/versions/{version_id}/process`
- `GET /api/v1/versions/{version_id}/pages`
- `GET /api/v1/versions/{version_id}/pages/{page_number}`
- `GET /api/v1/versions/{version_id}/pdf`

### Extraction

- `POST /api/v1/versions/{version_id}/extraction-runs`
- `GET /api/v1/extraction-runs/{run_id}`
- `GET /api/v1/extraction-runs/{run_id}/candidates`
- `GET /api/v1/candidates/{candidate_id}`
- `GET /api/v1/agreements/{agreement_id}/obligations`

### Human review and approved register

- `GET /api/v1/review/candidates`
- `GET /api/v1/review/candidates/{candidate_id}`
- `POST /api/v1/candidates/{candidate_id}/review-decisions`
- `GET /api/v1/obligations`
- `GET /api/v1/obligations/{obligation_id}`
- `GET /api/v1/obligations/{obligation_id}/revisions`

### Monitoring

- `GET /api/v1/monitoring-periods`
- `POST /api/v1/obligations/{obligation_id}/monitoring-periods`
- `GET /api/v1/monitoring-periods/{period_id}`
- `POST /api/v1/monitoring-periods/{period_id}/updates`

### Amendments and audit

- `POST /api/v1/agreements/{agreement_id}/amendment-comparisons`
- `GET /api/v1/agreements/{agreement_id}/amendment-comparisons`
- `GET /api/v1/comparison-items/{item_id}/removal-review`
- `POST /api/v1/comparison-items/{item_id}/decisions`
- `GET /api/v1/audit-events`

The routers expose GET/POST operations only; there are no general destructive delete endpoints. The architecture document provides request/response examples for important routes.

## 4. PDF ingestion and AI extraction

Upload checks PDF signature, encryption, size, and page-count limits, stores the original bytes, and records the SHA-256. PyMuPDF extracts text page by page and stores page number, extraction method, warnings, text, and text hash. Empty/selectable-text-free pages are flagged; OCR is not implemented. The document version and original PDF can be retrieved within the workspace scope.

Extraction is explicitly started for a processed version. Page-mapped chunks are bounded by configured size/overlap/maximums and all nonblank chunks are sent for analysis; lexical screening is disabled to avoid false negatives. The service calls the configured provider with a versioned prompt and JSON schema, validates canonical payloads, resolves supported references, verifies evidence pages and quote presence, and saves immutable candidates plus evidence. Provider/model/run metadata and chunk coverage are retained. Runs exceeding the configured maximum are partial and report unprocessed chunks; no extractable text is a failure rather than an empty-covenant conclusion.

**Provider status:** the configured model was `openai/gpt-6.1-terra` with the configured OpenRouter base URL. The key was confirmed present without reading or printing its value. One real request for a synthetic agreement returned HTTP 402 (`provider_insufficient_credits`); the run ended `partial`, returned no candidates, and did not validate model output. The sanitized result is recorded in `docs/LLM_LIVE_EVALUATION_2026-11-03.json`. Automated tests use a deterministic mock provider and are not LLM evaluations.

## 5. Definition and cross-reference resolution

Reference handling is deterministic and text-based. It identifies quoted or recognized financial terms, looks for definition verbs such as “means” and “shall mean”, collects nearby definition lines, finds explicit section-number references, and looks for matching section headings. Definition/reference text found in the document is added as evidence. Model-supplied text/pages are not accepted as proof; unavailable or unmatched definitions and targets are represented as `null` and add uncertainty reasons.

This is limited regex/heading lookup, not semantic resolution. Complex formatting, cross-page definitions, nested schedules, unusual defined-term styles, and OCR content may remain unresolved or be misidentified. Uncertainty routes to review.

## 6. Human review and approval

The review queue shows candidate payload, findings, evidence, and source page text. Admin/reviewer identities can approve, reject, request information, or correct. `corrected_obligation` is a complete replacement object validated as the canonical `$defs.obligation` object; it is not a patch or a batch envelope. The full payload and evidence are validated again before approval. Candidates remain immutable. Approval creates a distinct approved obligation revision and corresponding evidence rows transactionally. Revisions preserve the full approved payload and history.

Backend/API behavior is covered by workflow tests, including approval and correction paths. Frontend review/approval interactions are tested with mocked API responses, not a live browser-to-API end-to-end test.

## 7. Quarterly monitoring

Monitoring periods are tied to an approved obligation revision and include period boundaries, due date/rule, status, and append-only update history. Canonical statuses are `awaiting_setup`, `upcoming`, `due`, `awaiting_evidence`, `submitted`, `reviewed`, `not_assessed`, and `not_applicable`. `overdue` is derived from due date and open status, not stored as an independent judgment.

Contributors can create periods and record progress through `submitted`; reviewer/admin can record assessment outcomes; read-only users cannot mutate. Backend tests cover allowed and prohibited roles. Only a narrow calendar-day deadline subset is resolved automatically; ambiguous and business-day deadlines need reviewer configuration. The app does not assess covenant compliance or calculate ratios.

## 8. Amendment comparison

Comparison uses deterministic category/name and similarity matching to propose additions, changes, possible matches, unresolved items, or removals. It stores run status, chunk counts (including unprocessed and screened-out), document page count, extracted page count, and pages with text.

An unmatched approved obligation is `unresolved` when run/document coverage is incomplete. Complete processing coverage may produce a *proposal* but is not evidence of legal removal. For unresolved/removal items the API returns prior approved payload/evidence, amendment version, coverage, and complete extracted page text; the original PDF can be fetched for inspection. Reviewer/admin acceptance requires an explicit full-document review confirmation and a written explanation. The prior obligation remains active until acceptance; the decision and audit event are retained.

An intentionally omitted clause in a partial-extraction test remained unresolved and active until confirmation. Residual risks remain: the extraction can miss clauses even when all chunks are processed, and text-similarity matching can generate false or missed matches. In the current conservative rule, any screened-out chunk prevents complete-coverage removal classification, so some otherwise unrelated-document cases remain unresolved and require manual review.

## 9. Audit history

Workflow actions record actor, action, entity, time, request identifier where available, and summary. The audit endpoint is workspace-scoped and filterable. ORM event handlers prevent update/delete through the normal application ORM path. There is no external tamper-evident ledger, retention/export workflow, or production privileged-access control; the audit trail should not be described as cryptographically immutable.

## 10. Evaluation dataset and results

`backend/tests/fixtures/synthetic_evaluation_dataset.json` contains 10 synthetic cases and 10 expected canonical obligations, with source excerpt, page, section, and supporting quote. It covers leverage, interest coverage, liquidity, quarterly reporting, annual audit, capex, additional indebtedness, definitions/references, a conditional exception, and an ambiguous deadline. The evaluator checks schema and evidence/quote/page integrity.

**Executed fixture result:** 10 examples, 10 expected obligations, integrity passed with 0 errors. This is annotation/schema integrity only. No model prediction file or live provider result was evaluated. LLM detection precision/recall, field accuracy, threshold/deadline accuracy, citation accuracy, definition resolution, escalation accuracy, and legal correctness are **not measured**. Mock-provider tests are software behavior tests, not an accuracy benchmark.

Failure scenarios tested/documented include intentionally omitted clauses in partial amendment extraction, invalid schema/evidence, missing/unresolved references, and ambiguous deadlines. No incorrect live-provider extraction or citation result was observed because no live provider evaluation was run.

## 11. Backend test results

Executed commands and exact outcomes:

| Command / working directory | Result |
| --- | --- |
| `python -m pytest -q backend/tests` from repository root | **45 passed**, exit 0; one Starlette/httpx deprecation warning. |
| `python -m pytest -q tests` from `backend/` | **45 passed**, exit 0; same warning. |
| `python -m pytest -q tests/test_workflows.py` from `backend/` | **11 passed**, exit 0; same warning. |
| `python -m pytest -q tests/test_cors.py` from `backend/` | **7 passed**, exit 0; preflight configuration, custom port, and wildcard rejection covered. |
| `python -m compileall -q app tests scripts` from `backend/` | Exit 0. |
| `python -m pytest -q tests/test_synthetic_evaluation.py` from `backend/` | **1 passed**, exit 0; same warning. |

The suites use temporary test databases and deterministic mock extraction providers. API tests use FastAPI's TestClient and isolated databases; they do not exercise a live PostgreSQL service or live external LLM.

## 12. Frontend installation, tests, build, and browser integration

- The active dependency-lock candidate was Node/Vite PID **22832**, listening on 5173 and referencing this repository's Vite and `node_modules`. Only that identified project process was stopped; unrelated Node processes were left running.
- `npm ci` in `frontend/`: **exit 0**, 224 packages installed, audit reported 0 vulnerabilities. `package-lock.json` was not intentionally changed.
- `npm test` in `frontend/`: **5 passed**, exit 0. These workflow tests use mocked fetch responses.
- `npm run build` in `frontend/`: **exit 0**, Vite transformed 17 modules and produced the production bundle.
- CORS uses `FRONTEND_PORT` and explicit `CORS_ALLOWED_ORIGINS`; with `FRONTEND_PORT=5177`, live OPTIONS preflight returned HTTP 200 and echoed `http://127.0.0.1:5177`. Vite uses the same configured port with `strictPort: true`; wildcard origins are rejected.
- The first test attempt after the Vite config edit failed because `loadEnv` was imported from `vitest/config`. The import was corrected to come from `vite`; the final tests/build above passed.

**Actual browser UI workflow:** not completed. The Computer Use browser helper stopped before navigation because it could not confidently determine Chromium's current URL and instructed the automation to stop. Therefore no claim is made that a browser performed agreement creation, upload, review, monitoring, amendment, or audit interactions.

**Live HTTP integration (not a browser test):** frontend dev server returned HTTP 200 on `127.0.0.1:5177`; API health returned `{"status":"ok"}` on port 8001. A real preflight to the API from `http://127.0.0.1:5177` returned HTTP 200 and `Access-Control-Allow-Origin: http://127.0.0.1:5177`. A temporary `httpx` workflow sent the same `Origin` header on actual requests, checked the matching CORS response on each, and completed agreement creation, multipart PDF uploads, processing, extraction using a deterministic mock provider, review correction/approval, register read, monitoring period/submission, amendment comparison/acceptance, audit read, and SQLite row-count checks. It verified 2 versions, 2 page rows, 2 runs, 2 candidates, 1 obligation, 2 revisions, 8 evidence rows, 1 monitoring period/update, 1 comparison/item/decision, and 15 audit events.

The integration script's initial summary expression incorrectly printed `page_text_quote_verified: false`; a follow-up direct API page read verified that page text was present and its hash matched the page-list hash. This was an audit-script reporting error, not an application response failure. The integration instance used an isolated SQLite database and synthetic PDFs. Temporary files and services were stopped/removed after the test.

## 13. Database migration and PostgreSQL verification

A fresh disposable SQLite database was migrated with `alembic upgrade head`, then checked with `alembic current`. Both commands exited 0 and the reported head was `0004_amendment_review_safety`. The full synthetic HTTP integration also persisted to a separate disposable SQLite database. Existing local databases were not reset or migrated.

PostgreSQL verification was **not run**. Exact environment checks found: Docker command unavailable, `psql` unavailable, `postgres` executable unavailable, zero PostgreSQL services, and no listener on TCP 5432. Consequently Docker Compose could not start PostgreSQL, and no PostgreSQL migration or backend integration suite can be claimed as passed. No existing database was deleted or modified.

## 14. Docker verification

`docker compose config` exits 1 because `docker` is not installed. Docker Compose configuration/build/runtime and PostgreSQL-in-Compose remain unverified. Compose requires a local `POSTGRES_PASSWORD` and optionally OpenRouter credentials; `.env.example` contains placeholders only.

## 15. Security and secrets audit

- Secret-pattern scan over application source and configuration (excluding dependencies, generated build output, and `.env`): **no matches**. The scan did not print secret values.
- Private-key/certificate scan: **0 key/certificate files** and **0 private-key PEM markers**.
- `.env` present: **Yes; contents were not read or printed**.
- `.env.example` credential values: **placeholders only**.
- `.gitignore`: present; excludes environment files, database extensions, storage/uploads, node modules, build output, Python caches, and test temporary directories.
- Local database and runtime storage contain synthetic demo PDFs and workflow records; these are ignored and must remain out of any public commit.
- Local database-like files found: **29**; these include a root development database, a backend migration-check database, and temporary test databases. They were not deleted or inspected as part of this audit and must not be committed publicly.
- PDF files found: **16**, under `.pytest-*` temporary upload directories; they are generated synthetic test PDFs, not private agreements. Keep these artifacts out of any public commit.
- `.git` directory: **absent**. Tracked/staged content and Git history could not be audited. No push or Git-history change was performed.

## 16. Known bugs and incomplete functionality

1. The live OpenRouter call returned HTTP 402 for insufficient credits; no real model result was produced, so model compatibility, extraction quality, evidence fidelity, and quality metrics remain unverified.
2. Frontend tests use mocked HTTP responses. The workflow was exercised through real HTTP requests with CORS against a live local backend, but not through a browser UI; browser automation stopped because it could not establish the current browser URL confidently.
3. No unresolved dependency-install issue remains: the identified project Vite process holding dependency files was stopped and clean `npm ci` completed successfully. Windows file locking could recur if a development server is left running during reinstall.
4. CORS is now configurable through `FRONTEND_PORT` and `CORS_ALLOWED_ORIGINS`, with explicit loopback defaults and wildcard rejection. A custom-port live preflight passed.
5. OCR is absent; image-only pages yield no selectable text and cannot support reliable extraction.
6. Definition and cross-reference resolution is regex/heading-based; complex references remain unresolved or may be missed.
7. Deadline calculation is narrow; business-day and qualitative rules require manual configuration.
8. Amendment matching is heuristic and extraction completeness does not guarantee recall. Human review is still required across the full document.
9. Audit append-only protections are ORM-level, not tamper-proof against direct database access.
10. Development identity selection is not production authentication. Production deployment requires identity/session design, secrets management, private storage controls, and security review.
11. PostgreSQL and Docker were not available for integration verification.
12. The current workspace is not a Git repository, so public commit contents cannot be checked until a staging area exists.

## Current final-verification disposition

- Backend test suite: 47 passed in 12.13s, exit 0 after final provider error handling changes; earlier CORS-specific suite: 7 passed, exit 0; compileall: exit 0.
- Frontend: clean `npm ci` was previously verified; 7 tests passed after adding the provider-error display test, and production build exited 0. `package-lock.json` was not intentionally edited.
- Live local HTTP workflow: passed against an isolated SQLite database and deterministic mock provider, including create/upload/process/extract/review/approval/register/monitoring/amendment/audit. This was not a browser UI test.
- PostgreSQL/Alembic against PostgreSQL: not run because Docker, `psql`, and `postgres` are unavailable and there is no listener on 5432. SQLite migration verification is not evidence of PostgreSQL compatibility.
- OpenRouter: the key was present (value never printed), and one synthetic-only extraction attempt returned HTTP 402 insufficient credits. No candidate was produced. No private agreement was sent externally. The actual response and error are recorded in `docs/LLM_LIVE_EVALUATION_2026-11-03.json`.
- Security: `.env` is present and ignored; its contents were not read. `.env.example` has credential placeholders; no credential patterns were found in source/config scans and no private-key PEM artifacts were found. Local databases and synthetic PDF artifacts remain in the workspace and must be excluded from any public commit. `.git` is absent, preventing a tracked/staged file audit.
- Error audit trail: the 402 run's original application audit event recorded status/count only because it predated the error-metadata allowlist fix. A supplemental database audit row was not added: the approval reviewer rejected that action as modifying existing data. The sanitized evaluation JSON records the exact reason, and new provider-failure audit events now retain the safe error code, HTTP status, and summary; this is covered by backend tests.

## Run commands

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
# Set local DATABASE_URL / POSTGRES_PASSWORD and optional OpenRouter values in .env.
cd backend
alembic upgrade head
python -m uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`; the API health endpoint is `http://localhost:8000/health`. Use a disposable development database and public or synthetic documents only. Do not use the seeded development identities with private agreements or deploy them as production authentication.
