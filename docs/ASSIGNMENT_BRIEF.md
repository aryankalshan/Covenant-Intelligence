# Covenant Intelligence — Assignment Brief

## Page 1 — Problem and proposed solution

Corporate credit agreements contain financial tests, reporting deadlines, and restrictions across lengthy, amended documents. Finance teams need a reliable way to find obligations, retain the source language, and track recurring evidence and review.

Covenant Intelligence is a finance workflow prototype that ingests public or synthetic PDF agreements, extracts page text, generates evidence-backed draft obligations, and presents them for human review. Approved obligations form a versioned register that can be monitored by reporting period. Amendment comparisons create review proposals and preserve agreement history.

Target users include corporate treasurers, finance directors, corporate finance teams, and compliance teams. The prototype is decision support only. It does not provide binding legal advice, calculate covenant ratios or headroom, or connect to ERP systems.

## Page 2 — Architecture and division of work

The system is a modular monolith: React, TypeScript, and Tailwind CSS frontend; FastAPI/Python backend; PostgreSQL through SQLAlchemy and Alembic; PyMuPDF for page extraction; Pydantic for validation; OpenRouter behind an OpenAI-compatible provider adapter. Docker Compose is an optional local infrastructure path.

**AI proposes.** It reads bounded text chunks and returns candidate obligations in a versioned JSON contract. Each candidate must cite a page and quote. Model confidence is not treated as proof.

**Deterministic code checks and records.** It validates schema shape, evidence page existence and quote presence, supported definitions/references, role permissions, monitoring status transitions, and amendment extraction coverage. It preserves the original candidate and approved payload separately, with corresponding evidence rows in the same transaction.

**People decide.** A reviewer can approve, correct, reject, or request information. No candidate is auto-approved. Contributors can submit monitoring progress; reviewer/admin roles own assessment decisions. Seeded identities are development-only and do not provide production authentication.

## Page 3 — Human review, amendments, and risks

The reviewer sees source pages, evidence, warnings, and uncertainty before approving. A correction replaces the complete canonical obligation object and is validated again. Approved revisions retain their entire payload, source evidence, reviewer, and history.

Quarterly monitoring captures period dates, due dates where deterministically resolvable, evidence references, and canonical statuses. Overdue is derived from the date and open status. The product does not declare financial covenant compliance or compute ratios.

Amendment matching is intentionally a proposal mechanism. Coverage details include processed, unprocessed, and screened chunks plus page text availability. An unmatched prior covenant in incomplete extraction is unresolved. Even complete extraction coverage does not prove removal. A reviewer must inspect the original amendment PDF, attest to reviewing every page, and explain acceptance. The original record remains active until accepted.

Key limitations include model omissions or misinterpretation, incomplete OCR support, limited definition lookup, ambiguous deadlines, false amendment matches, synthetic-only evaluation, local development identity, and no production security review. Evidence matching establishes traceability, not legal correctness.

## Page 4 — Evaluation and owner contribution

The repository includes ten synthetic cases covering leverage, interest coverage, liquidity, quarterly statements, annual audit, capex, indebtedness, definitions/cross-references, exceptions, and ambiguous timing. The evaluator validates that expected objects meet the canonical schema and citations match the synthetic excerpt. These fixture checks do not measure model accuracy.

No live provider benchmark has been run for this submission. Precision, recall, field extraction, threshold/deadline accuracy, citation accuracy, definition resolution, and escalation accuracy remain unmeasured until actual provider output is scored. Pytest and frontend test/build outcomes are reported separately as software verification, not AI quality.

**Owner contribution (complete in your own words before submission):**

- Engineering decisions I made: [Add your decisions.]
- Code I personally reviewed and corrections I made: [Add specific work.]
- What I learned or would change next: [Add your own reflection.]
- Other material assistance: [Disclose accurately.]

AI assistance was used in drafting and revising repository code and documentation. Review `docs/LLM_USAGE.md` and ensure this brief accurately reflects your own contribution and understanding before submitting.
