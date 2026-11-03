# Project instructions

## Project scope

Covenant Intelligence is a corporate finance take-home design for turning public or synthetic corporate credit agreement PDFs into evidence-backed draft obligations and a human-reviewed quarterly monitoring register. Maintain the stated modular monolith architecture unless requirements change.

## Domain constraints

- Do not calculate actual financial ratios or covenant headroom.
- Do not integrate with ERP systems.
- Do not present output as binding legal advice.
- Use public or synthetic documents only in examples, fixtures, and demos.
- Never invent clauses, thresholds, definitions, deadlines, or citations.
- Every extracted obligation must retain source evidence tied to an immutable agreement version and page.
- Uncertain or invalid extractions require human review. Never automatically approve an extracted obligation.
- Keep original model candidates distinct from human-approved records; retain correction and amendment history.

## Architecture and implementation guidance

- Keep document processing, extraction/provider integration, validation, persistence, and business rules in separate backend modules.
- Use deterministic validation for schema, evidence page, and quote existence. Treat this as traceability validation, not legal correctness.
- Preserve original PDF bytes and agreement version history. Make changes to approved obligations through new revisions.
- Keep OpenRouter behind a provider adapter; version prompts and output schemas. Do not place secrets in the repository.
- Keep API Pydantic schemas separate from SQLAlchemy persistence models and domain rules.
- Require explicit authorization checks for workspace-scoped data at the API/use-case boundary.
- Avoid microservices and autonomous agents unless requirements and measured load justify a change.
- Do not add OCR, ratio calculation, ERP connectivity, or automatic approval without an explicit scope change.

## Documentation and changes

- Keep `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, and `docs/DESIGN_DECISIONS.md` aligned when design decisions change.
- Keep `docs/EXTRACTION_SCHEMA.md` aligned with the extraction models, API contract, and documented schema version.
- Favor readable, small modules and explicit status transitions.
- Record consequential design changes and their rationale.
- Tests are mandatory for every newly implemented feature.
- Add relevant Pytest tests for backend functionality, including business rules, authorization, and API behavior where applicable.
- Add frontend tests for important user workflows, especially upload, review/approval, register, and monitoring interactions.
- Never claim tests passed unless they were executed; report the exact commands and outcomes.
