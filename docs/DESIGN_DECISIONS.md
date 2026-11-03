# Covenant Intelligence — Design Decisions

This document records initial decisions for the take-home design. They are provisional where the assignment has not specified deployment or scale. They do not authorize production use of private agreements.

## Step 4/5 safety refinements

### Explicit, configurable local CORS origins

The API allows only explicit HTTP(S) origins. In development it derives `http://localhost:{FRONTEND_PORT}` and `http://127.0.0.1:{FRONTEND_PORT}`; `CORS_ALLOWED_ORIGINS` can replace that list. Vite reads the same `FRONTEND_PORT` and uses strict-port mode so it cannot silently move to an origin the API has not allowed. Wildcard origins are rejected.

### Amendment absences require full review

An unmatched covenant in a partial or incomplete extraction is `unresolved`, never a definite removal. A complete-coverage match failure may only create a proposal; an authorized reviewer must inspect the full source PDF, attest to that review, and explain acceptance. This favors false uncertainty over silently dropping an obligation. Coverage details and decisions are persisted for audit.

### Role-specific monitoring decisions

Contributors initialize periods and submit progress/evidence; reviewers/admins control assessment outcomes; read-only identities have no mutation endpoints. API checks remain authoritative and UI controls mirror them. Development identities are convenience fixtures only.

### Synthetic evaluation before provider claims

The checked-in 10-example set tests gold-label schema and evidence integrity. It is not used to claim model performance. Provider metrics require saved real provider predictions scored against these labels, with the provider/model, prompt, schema, and run context retained.

## Decisions

### 1. Modular monolith

**Decision:** React client plus one FastAPI backend, with domain modules and explicit interfaces.

**Reason:** The workflow is cohesive and the expected take-home scale does not justify distributed services. In-process boundaries keep development and deployment simple while allowing later extraction of a measured bottleneck. Docker Compose provides local PostgreSQL and app services.

**Alternative:** Separate document, extraction, and monitoring services. Rejected initially because service orchestration, network failure modes, and distributed transactions would add cost without demonstrated need.

### 2. Immutable agreement versions and provenance-first records

**Decision:** Preserve uploaded bytes and each agreement version; attach each evidence item to a version, page, and quote. Model amendment revisions as new records.

**Reason:** Citations must remain reproducible, and amendment history must not erase the prior basis for an obligation. Content hashes help identify duplicate uploads and detect corruption.

**Alternative:** Store only extracted text or replace an agreement when amended. Rejected because neither preserves a trustworthy source citation and version history.

### 3. Separate model candidates from approved obligations

**Decision:** Persist extraction runs/candidates as immutable drafts; human review creates or revises the approved register.

**Reason:** Models can omit or misinterpret legal text. Review status is an explicit business control; no confidence score can approve a covenant.

**Alternative:** Treat the best model result as the current register with a correction field. Rejected because it blurs provenance and human authority.

### 4. Evidence required and validated deterministically

**Decision:** Every candidate must cite one or more page-level quotes. Validate page existence and quote containment against extracted text; preserve unresolved references and uncertainty for human review.

**Reason:** This makes fabrication detectable and review practical. Deterministic checks confirm that cited text exists, but do not establish that it legally supports the interpretation.

**Alternative:** Rely on model confidence or ask the model to cite pages without validating them. Rejected because generated citations can be wrong.

### 5. PyMuPDF for initial text extraction; OCR deferred

**Decision:** Use PyMuPDF for digital text PDFs, track empty/low-text pages, and report incomplete extraction. Keep an OCR adapter as an optional extension.

**Reason:** The requested stack includes PyMuPDF and the initial scope should be inspectable. OCR adds quality, cost, and provenance considerations.

**Alternative:** Automatically OCR every page. Defer until representative sample documents establish need and acceptable accuracy. Any OCR output must record engine/version and remain evidence tied to the source page.

### 6. OpenRouter behind a provider interface

**Decision:** Use an OpenAI-compatible client adapter with configurable model/provider settings, prompt/schema versions, timeouts, and explicit failure states.

**Reason:** Provider behavior and model availability can change. The domain extraction pipeline should not depend directly on a specific SDK or response format.

**Alternative:** Call provider endpoints from route handlers or hardcode a single model. Rejected because it couples business logic to vendor details and makes versioning/replacement difficult.

### 7. Strict structured output plus deterministic validation

**Decision:** Ask the model for typed structured candidates and parse them through Pydantic, then run domain validators for evidence and required fields.

**Reason:** Schema validity is necessary for a usable register but is not enough to establish correctness. Uncertain or malformed results remain drafts.

**Alternative:** Use free-form prose and parse it downstream. Rejected because it makes validation and correction harder.

### 8. Human-driven quarterly monitoring

**Decision:** Track obligation periods, deadlines, status updates, notes, and optional supporting references. No ERP integration and no actual ratio computation.

**Reason:** The application tracks whether an obligation is due/reported; it does not derive covenant compliance from borrower financials. Ambiguous deadline rules remain unresolved until a human confirms them.

**Alternative:** Ingest financial statements and calculate ratios or covenant headroom. Explicitly outside assignment scope and creates additional data/security and legal interpretation risk.

**Status vocabulary:** `awaiting_setup`, `upcoming`, `due`, `awaiting_evidence`, `submitted`, `reviewed`, `not_assessed`, `not_applicable` is shared across persistence, API, and frontend. `overdue` is derived when the due date has passed and status is `awaiting_setup`, `upcoming`, `due`, or `awaiting_evidence`; it is never a separately stored or manually selected compliance status. `submitted` remains submitted while pending review.

### 9. Amendment comparison creates proposals only

**Decision:** Compare a newly processed version against approved obligations and present possible additions, changes, and removals for human decision.

**Reason:** Textual similarity cannot guarantee legal effect. A human must accept each resulting register change.

**Alternative:** Automatically update the live register based on semantic similarity. Rejected because false matches can conceal a material amendment.

### 10. PostgreSQL and SQLAlchemy with Alembic

**Decision:** Use PostgreSQL as system of record, SQLAlchemy for persistence, Alembic for schema evolution, and Pydantic for API and extraction validation.

**Reason:** This matches the requested stack and provides relational integrity for version/evidence/review relationships. JSON columns are limited to evolving extraction fields; core relationships and status remain relational.

**Alternative:** Store the entire application state as document blobs. Rejected because approvals, audit, and period tracking need queryable relationships and constraints.

### 11. Development-only seeded identity for the MVP

**Decision:** Seed one development workspace and development reviewer identities. Resolve each request to a seeded identity and enforce workspace-scoped role authorization in the backend.

**Reason:** This makes review and authorization flows demonstrable within the take-home while avoiding a claim of production identity security.

**Limitation:** This mechanism is strictly development-only authentication, not production identity management. Production use requires a real identity provider, session/token security, and a security review.

### 12. Versioned extraction contract and explicit nulls

**Decision:** Use the canonical JSON Schema in `EXTRACTION_SCHEMA.md` (currently `1.1.0`), persist its version with each run, require evidence, and represent unavailable information as `null`. The additive 1.1.0 update adds `affirmative_covenant` as a distinct category for insurance, compliance, and similar affirmative obligations.

**Reason:** Versioned structured output makes validation and review reproducible. Evidence is validated against page text, but neither the presence of a quote nor any model confidence proves that the interpretation is correct.

**Alternative:** Let provider-specific response formats define the contract or treat confidence as a correctness score. Rejected because output behavior would be inconsistent and confidence cannot replace human review.

## Open decisions before implementation or deployment

- Identity provider, organization/tenant boundaries, and role assignment.
- Production authentication/session mechanism; the seeded identity mechanism is development-only.
- Maximum PDF size/page count, supported languages, and whether encrypted PDFs are rejected.
- Whether scanned documents require OCR for the take-home demo.
- Provider/model selection, prompt retention, data residency, and OpenRouter data-use terms for any real agreement content.
- Local filesystem versus private object storage in deployment; encryption and retention/deletion requirements.
- Background job mechanism if synchronous extraction exceeds acceptable request times.
- Calendar/deadline interpretation policy (business days, holidays, fiscal quarters) and who can confirm a rule.
- Audit retention and export requirements.

## Validation principles

- Do not fabricate clauses, thresholds, definitions, deadlines, or page citations.
- A quote being present on a page does not prove the candidate interpretation is correct.
- Every unresolved definition, ambiguous trigger, or uncertain deadline should be visible and require review.
- No extracted obligation is automatically approved.
- No feature should compute borrower financial ratios or integrate to ERP systems within the stated scope.

### 13. Complete immutable payload plus relational evidence

**Decision:** Retain the full versioned canonical obligation object on every candidate and approved revision, and also store its supporting evidence as relational page-linked rows in one transaction.

**Reason:** The JSON payload provides faithful schema-versioned provenance while relational evidence provides queryable joins and integrity checks. Atomic persistence prevents either representation getting ahead of the other. Candidate objects are immutable; corrections create separate approved revisions.

**Alternative:** Store only normalized fields or only JSON evidence. Rejected because either loses complete model output or weakens page/version referential integrity.

### 14. Bounded, human-reviewed monitoring and amendment changes

**Decision:** Use one shared eight-state monitoring vocabulary, derive overdue from dates/status, support only deterministic unambiguous calendar-day deadline calculations, and treat amendment matching as proposal generation requiring reviewer decisions.

**Reason:** The system must not imply actual covenant compliance or legal effect from heuristics. Complex dates and uncertain matches remain for humans to resolve.

**Limitation:** All nonblank chunks are now sent for extraction to avoid keyword-screening false negatives, but a configured chunk cap can still leave long documents partially unprocessed; OCR is not enabled; name/category amendment matching can miss or mispair obligations. No result or absence of a result establishes legal correctness or completeness.
