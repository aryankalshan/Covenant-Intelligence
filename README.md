# Covenant Intelligence

Covenant Intelligence ingests public or synthetic corporate credit agreement PDFs, extracts page text, and produces evidence-backed AI draft candidates for financial covenants, reporting duties, and negative covenants. Candidates remain unapproved and must be checked by a human. The application does not calculate actual financial ratios, connect to ERP systems, or provide binding legal advice.

## Requirements and installation

- Python 3.12+
- Node.js 20+ and npm
- PostgreSQL 16+ for PostgreSQL mode; local SQLite is supported for development and tests
- Optional: Docker Compose
- Optional: OpenRouter account and an enabled model with JSON Schema structured output

Install packages:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

Copy `.env.example` to `.env`. The example contains placeholders only. Leave `DATABASE_URL` blank to use the project-root SQLite file, or set it to a PostgreSQL URL. Configure `STORAGE_DIR` and upload/page limits as needed. `FRONTEND_PORT` defaults to 5173; the backend allows explicit loopback origins for that port. Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of exact HTTP(S) origins to override the defaults (for example, `http://localhost:5174,http://127.0.0.1:5174`). Vite uses the same `FRONTEND_PORT` and fails instead of silently switching ports. For live extraction set `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and optionally `OPENROUTER_BASE_URL`, request timeout, retries, and chunk bounds. Keys stay on the backend and must never be added to frontend variables or source control. A missing provider configuration is reported as an extraction failure; tests use a deterministic mock provider.

## Database and migrations

Default local settings use `sqlite:///./covenant.db`; source PDFs are written to `./storage/`. Both paths are excluded from Git. To use PostgreSQL, set a local URL such as `postgresql+psycopg://covenant:<local-password>@localhost:5432/covenant_intelligence` in `.env`. Do not use private agreements in the development workspace.

Migrations are the only application schema authority. From `backend/`:

```powershell
alembic upgrade head
alembic current
```

Application startup seeds the development workspace and identities only; it does not create or alter schema. Docker Compose applies migrations before starting the API. Set `POSTGRES_PASSWORD` in `.env` before `docker compose up --build`.

## Start the application

Run the API from `backend/` after migrating:

```powershell
cd backend
alembic upgrade head
python -m uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`; API health is available at `http://localhost:8000/health`. The web client defaults to the seeded `contributor` identity so agreement creation and upload are available; the same selected identity is sent in `X-Dev-User`. Reviewer/admin roles are available for approval and assessment decisions. These are development-only identity switches, not authentication or production identity management. Workspace checks are enforced by API routes. Do not deploy this mechanism or use real/private agreements with it.

## Main workflow

1. Create an agreement as a contributor/admin.
2. Upload a public or synthetic PDF version and process its page text.
3. Inspect extracted text and its page hash.
4. Start covenant extraction for a processed version.
5. Review AI candidates, cited page quotes, definitions, and validation warnings. Authorized reviewers can approve, correct, reject, or request information; candidates remain separate from immutable approved revisions.
6. Create quarterly monitoring periods, record contributor evidence/progress, and let reviewers record assessment decisions.
7. Compare an amendment with the approved register. Missing matches remain unresolved when extraction coverage is incomplete; any removal proposal requires inspection of the complete amendment and an explicit reviewer confirmation and explanation.
8. Inspect audit history for recorded workflow decisions.

The extraction run uses bounded page-mapped chunks, OpenRouter structured output, deterministic schema/domain checks, direct source quote matching, and deterministic definition/section lookup. Every candidate and its relational Evidence rows are saved in one transaction. The canonical contract is `docs/EXTRACTION_SCHEMA.md` version 1.0.0.

## Tests and checks

Backend:

```powershell
cd backend
python -m pytest -q
python -m compileall -q app tests
```

Fresh migration verification (use a disposable path):

```powershell
$env:DATABASE_URL = "sqlite:///./migration-fresh.db"
alembic upgrade head
alembic current
```

Frontend:

```powershell
cd frontend
npm test
npm run build
```

The tests use synthetic documents and a mock provider. Live OpenRouter calls require user-supplied backend credentials and incur provider usage; they are not part of automated tests.

## Synthetic evaluation

The 10-case gold set is `backend/tests/fixtures/synthetic_evaluation_dataset.json`. Run its annotation/schema/evidence integrity check with:

```powershell
cd backend
python -m scripts.evaluate_synthetic_dataset
```

This check is not an LLM benchmark. Precision, recall, field accuracy, citation accuracy, deadline/definition accuracy, and escalation accuracy remain unmeasured until real provider predictions are saved and scored with `--predictions <path>`. See [Evaluation](docs/EVALUATION.md) and [LLM usage](docs/LLM_USAGE.md).

## Complete validation commands

From the repository root: `python -m pytest -q backend/tests`. From `backend/`: `python -m pytest -q tests`, `python -m compileall -q app tests scripts`, and for a fresh disposable SQLite DB `$env:DATABASE_URL='sqlite:///./migration-fresh.db'; alembic upgrade head`. From `frontend/`: `npm ci`, `npm test`, and `npm run build`. Docker Compose can be checked with `docker compose config` where Docker is installed. Never point the fresh-migration command at an existing development database.

## Scope limits

Current implementation includes PDF ingestion, AI extraction runs/candidates, evidence validation, human review and correction, approved obligation revisions, quarterly monitoring, deterministic amendment proposals with reviewer decisions, and audit history. LLM outputs remain drafts. Amendment comparison uses conservative name/category matching; it is not semantic legal analysis. See the architecture, data model, and canonical extraction schema documents for workflow and contract details.
