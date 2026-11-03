# Step 4 Implementation Report

**Project:** Covenant Intelligence  
**Review package:** `Covenant-Intelligence-Step4-Review.zip`  
**Scope:** Step 3 extraction reliability fixes and Step 4 human review, register, monitoring, amendments, and audit. No later phase is included.

## Step 3 issues fixed

- Definition lookup now verifies definition wording against normalized page text. Unsupported model-supplied definitions remain unresolved and carry uncertainty rather than being trusted.
- Cross-reference source wording and target headings are checked independently; target evidence and page are retained. Missing or unverified targets remain unresolved.
- Page-mapped chunking preserves source page context. New extraction runs submit every nonblank chunk; the chunk limit exposes any unprocessed remainder. Lexical screening is disabled to avoid false negatives.
- Alembic configuration uses a script location relative to its config file so migrations work from the repository root or backend directory.

## Step 4 functionality

### Human review

Reviewers/admins can view a candidate with cited page text, approve, correct using a complete replacement object, reject, or request information. Approval revalidates the canonical payload and source evidence. Extraction candidates are immutable; uncertainty must be resolved and explained before approval.

### Covenant register

Approved obligations are stored separately from AI candidates. The register supports agreement/category/search filters and sorting, displays canonical payload data, and exposes revision history and relational evidence.

### Quarterly monitoring

Users initialize periods for active approved obligations and record status updates, notes, evidence references, and evidence dates. Stored statuses are `awaiting_setup`, `upcoming`, `due`, `awaiting_evidence`, `submitted`, `reviewed`, `not_assessed`, and `not_applicable`. Overdue is derived from due date and open status. Only a narrow set of clear calendar-day period-end deadlines is calculated; ambiguous/business-day rules need a configured date.

### Amendment comparison

A processed amendment extraction can be compared with approved obligations. Deterministic category/name matching produces proposed additions, changes, possible matches, and removals. Admin/reviewer decisions are recorded; accepted changes are revalidated and create a revision. No proposal is applied automatically.

## Step 5 safety and evaluation addendum

Subsequent final-review refinements are captured in the current architecture and evaluation documents. Coverage now includes unprocessed and screened-out chunks and page text coverage. An unmatched prior covenant on incomplete coverage is unresolved, not removed. Removal acceptance requires a reviewer explanation and explicit full-document PDF review confirmation; prior evidence and version references are included in the review view. Monitoring status writes are role-scoped in the backend. The UI/API share a contributor default, with explicit reviewer/admin identities for review actions.

Ten authored synthetic examples now have canonical expected payloads and verifiable page quotations. The evaluator reports fixture integrity, while actual model precision/recall and field metrics remain unmeasured without real provider predictions. These are not claims of LLM performance. See `docs/EVALUATION.md`, `docs/LLM_USAGE.md`, and `docs/ASSIGNMENT_BRIEF.md`.

### Audit history

Workspace-scoped append-only application audit events are recorded for agreement/document actions, extraction, review, monitoring, and amendment decisions. Summaries use an allowlist and avoid source text and credentials.

## Database models and migrations

Added SQLAlchemy models for review decisions, monitoring periods/updates, amendment comparisons/items/decisions, and audit events. Extended obligations and revisions with lifecycle/current-revision/review references. Extraction candidates and approved revisions retain the complete canonical payload; supporting evidence rows are stored in the same database transaction. Alembic migration `0003_review_monitoring_audit` adds the corresponding schema and extraction coverage counters.

The existing local SQLite database was at `0002_extraction_metadata` and was migrated additively to `0003_review_monitoring_audit`; it was not reset. Before migration it contained zero agreements and zero document versions.

## API endpoints

All endpoints are under `/api/v1` and workspace-scoped:

- Agreements and versions: `GET/POST /agreements`, `GET /agreements/{id}`, `GET /agreements/{id}/versions`, `POST /agreements/{id}/versions`, `GET /agreements/{id}/versions/{version_id}`.
- PDF text: `POST /versions/{id}/process`, `GET /versions/{id}/pages`, `GET /versions/{id}/pages/{page_number}`.
- Extraction: `POST /versions/{id}/extraction-runs`, `GET /extraction-runs/{id}`, `GET /extraction-runs/{id}/candidates`, `GET /candidates/{id}`.
- Review: `GET /review/candidates`, `GET /review/candidates/{id}`, `POST /candidates/{id}/review-decisions`.
- Register: `GET /obligations`, `GET /obligations/{id}`, `GET /obligations/{id}/revisions`.
- Monitoring: `POST /obligations/{id}/monitoring-periods`, `GET /monitoring-periods`, `GET /monitoring-periods/{id}`, `POST /monitoring-periods/{id}/updates`.
- Amendments: `POST/GET /agreements/{id}/amendment-comparisons`, `POST /comparison-items/{id}/decisions`.
- Audit: `GET /audit-events`.

The review API's `corrected_obligation` is a complete object validated against `EXTRACTION_SCHEMA.md` `$defs.obligation`, not the batch envelope. Evidence is revalidated before approval.

## Frontend pages

The React app provides Dashboard, Agreements/document text, Covenant Register, Review Queue, Obligation Tracker, Amendment Comparison, and Audit History views. The review editor includes canonical fields and page evidence; monitoring and amendment decisions are submitted through the API. The development identity selector is for local demonstration only and is not production authentication.

## Tests and build results

Executed against synthetic fixtures and mocked extraction provider:

- `python -m pytest -q backend/tests` (from repository root): **35 passed, 1 warning**.
- `python -m pytest -q tests` (from `backend/`): **35 passed, 1 warning** in the documented working-directory run.
- `python -m compileall -q backend/app backend/tests`: completed successfully.
- `npm test` (from `frontend/`): **4 passed**.
- `npm run build` (from `frontend/`): completed successfully; TypeScript check and Vite production build passed.
- API smoke check with a temporary database: agreement creation `201`, PDF upload `201`, processing `200`, page text retrieval `200`; the returned page included extracted text, hash, and warnings.
- Alembic fresh-database migration is covered by Pytest; the existing database reports `0003_review_monitoring_audit (head)`.
- Docker verification: **not available**. `docker compose version` could not run because the `docker` command is not installed in this environment.

The Pytest warning is Starlette's deprecation warning for `httpx` with `TestClient`; it did not fail tests.

## Known bugs and incomplete features

No failing tests or confirmed reproducible blocking bugs were known at archive time. Remaining limits:

- No OCR for scanned PDFs. The configured chunk limit can leave long-document text unprocessed and marks coverage incomplete; an empty candidate list is not proof of absence.
- No live OpenRouter request was tested; automated tests use the deterministic mock provider.
- Deadline calculation does not handle business days, holidays, or ambiguous contractual rules.
- Amendment matching is deterministic heuristic matching and may miss or mispair provisions; every item requires review.
- Seeded `X-Dev-User` identities are development-only, not production authentication.
- Audit immutability is enforced at the application layer, not through a tamper-proof external ledger.
- Docker Compose and PostgreSQL deployment were not verified in this environment.
- The application does not calculate ratios, determine covenant compliance from financials, or integrate with ERP systems.
