# LLM Use and Attribution

## Where AI is used

The application sends bounded agreement text chunks through an OpenRouter adapter using an OpenAI-compatible structured-output request. The model proposes canonical obligation objects and supporting quotations. The extraction result is stored as an immutable draft candidate. It does not approve obligations, decide compliance, calculate ratios, or make a binding legal interpretation.

## Deterministic application responsibilities

Python/Pydantic validates the output schema. Deterministic checks validate that evidence pages exist, quotations are present on the cited page, definitions/cross-references are supported by document text, and explicit uncertainty is preserved. Database transactions store the candidate payload and corresponding relational Evidence rows together. Human reviewers correct, approve, reject, or request information. Amendment coverage and monitoring status permissions are also enforced by deterministic backend rules.

## Evaluation boundary

Tests use a deterministic mock provider and synthetic PDF excerpts. No live OpenRouter extraction benchmark was executed for this submission. Accordingly, real LLM precision/recall, field accuracy, deadline accuracy, citation accuracy, definition resolution, and escalation accuracy are not measured. `docs/EVALUATION.md` defines the reproducible ten-case synthetic set and scorer; only actual saved provider predictions may support a model-quality claim.

## Data and credentials

OpenRouter credentials remain backend-only in local environment configuration. Do not commit keys or send private financial documents in this development configuration. Use public or synthetic agreements only. Before any deployment, review provider data handling, retention, residency, access controls, and contractual terms. The seeded development workspace and `X-Dev-User` selector are not production authentication.

## Human contribution record

AI assistance was used to draft and revise implementation and documentation in this repository. The project owner should complete this section before submission with their own accurate account:

- **My engineering decisions:** [Describe decisions you made and why.]
- **My code review and corrections:** [List changes you personally inspected, tested, or revised.]
- **My understanding of the system:** [Explain the trade-offs and limitations in your own words.]
- **Additional tools or assistance:** [Disclose any other material assistance, or state none.]

Do not claim authorship of work you have not reviewed or understood.
