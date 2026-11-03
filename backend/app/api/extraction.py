from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_dev_membership, get_db, require_roles
from app.modules.audit.service import record_audit
from app.modules.agreements.models import Agreement, AgreementVersion
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.schemas import ExtractionCandidateOut, ExtractionRunOut, ExtractionRunRequest
from app.modules.extraction.service import run_extraction_background
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision

router = APIRouter(prefix="/api/v1")


def run_out(run: ExtractionRun) -> ExtractionRunOut:
    return ExtractionRunOut(
        id=run.id,
        agreement_version_id=run.agreement_version_id,
        status=run.status,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        schema_version=run.schema_version,
        chunk_count=run.chunk_count,
        unprocessed_chunk_count=run.unprocessed_chunk_count,
        screened_out_chunk_count=run.screened_out_chunk_count,
        processed_chunk_count=run.processed_chunk_count,
        candidate_count=run.candidate_count,
        validation_findings=run.validation_findings or [],
        error_code=run.error_code,
        error_summary=run.error_summary,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


def candidate_out(db: Session, candidate: ExtractionCandidate) -> ExtractionCandidateOut:
    run = db.get(ExtractionRun, candidate.extraction_run_id)
    evidence = list(db.scalars(select(Evidence).where(
        Evidence.candidate_id == candidate.id,
    ).order_by(Evidence.page_number, Evidence.id)))
    return ExtractionCandidateOut(
        id=candidate.id,
        extraction_run_id=candidate.extraction_run_id,
        status=candidate.status,
        validation_status=candidate.validation_status,
        validation_findings=candidate.validation_findings or [],
        canonical_payload=candidate.canonical_payload,
        extraction_origin=(
            "synthetic_demo" if run and run.provider == "synthetic_demo" else
            "mock_test" if run and run.provider == "mock" else
            "openrouter" if run and run.provider == "openrouter" else "provider"
        ),
        evidence=[{
            "id": item.id,
            "agreement_version_id": item.agreement_version_id,
            "page_number": item.page_number,
            "quote": item.quote,
            "source_section": item.source_section,
            "evidence_role": item.evidence_role,
        } for item in evidence],
    )


def scoped_run(db: Session, run_id: str, workspace_id: str) -> ExtractionRun:
    run = db.scalar(select(ExtractionRun).join(AgreementVersion).join(Agreement).where(
        ExtractionRun.id == run_id,
        Agreement.workspace_id == workspace_id,
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Extraction run not found.")
    return run


@router.post("/versions/{version_id}/extraction-runs", response_model=ExtractionRunOut, status_code=202)
def start_extraction(
    version_id: str,
    body: ExtractionRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_dev_user: str | None = Header(default=None),
):
    _, membership = current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)
    require_roles(membership, {"admin", "contributor"})
    version = db.scalar(select(AgreementVersion).join(Agreement).where(
        AgreementVersion.id == version_id,
        Agreement.workspace_id == membership.workspace_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    if version.status != "processed":
        raise HTTPException(status_code=409, detail="Process the document version before starting extraction.")
    run = ExtractionRun(
        agreement_version_id=version.id,
        status="queued",
        schema_version="1.1.0",
        requested_by=membership.user_id,
        requested_categories=body.categories,
    )
    db.add(run)
    db.flush()
    record_audit(db, workspace_id=membership.workspace_id, actor_user_id=membership.user_id,
                 action="extraction_started", entity_type="extraction_run", entity_id=run.id,
                 request_id=request.headers.get("X-Request-ID"), summary={"status": "queued"})
    db.commit()
    db.refresh(run)
    background_tasks.add_task(
        run_extraction_background,
        run.id,
        request.app.state.session_factory,
        request.app.state.provider_factory,
        max_chars=request.app.state.extraction_max_chars or 12_000,
        overlap_chars=request.app.state.extraction_overlap_chars or 1_000,
        max_chunks=request.app.state.extraction_max_chunks or 120,
    )
    return run_out(run)


@router.get("/extraction-runs/{run_id}", response_model=ExtractionRunOut)
def get_extraction_run(run_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)
    return run_out(scoped_run(db, run_id, membership.workspace_id))


@router.get("/extraction-runs/{run_id}/candidates", response_model=list[ExtractionCandidateOut])
def list_candidates(run_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)
    run = scoped_run(db, run_id, membership.workspace_id)
    rows = db.scalars(select(ExtractionCandidate).where(
        ExtractionCandidate.extraction_run_id == run.id,
    ).order_by(ExtractionCandidate.created_at, ExtractionCandidate.id))
    return [candidate_out(db, candidate) for candidate in rows]


@router.get("/candidates/{candidate_id}", response_model=ExtractionCandidateOut)
def get_candidate(candidate_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)
    candidate = db.scalar(select(ExtractionCandidate).join(ExtractionRun).join(AgreementVersion).join(Agreement).where(
        ExtractionCandidate.id == candidate_id,
        Agreement.workspace_id == membership.workspace_id,
    ))
    if candidate is None:
        raise HTTPException(status_code=404, detail="Extraction candidate not found.")
    return candidate_out(db, candidate)


@router.get("/agreements/{agreement_id}/obligations")
def list_approved_obligations(agreement_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)
    agreement = db.scalar(select(Agreement).where(
        Agreement.id == agreement_id,
        Agreement.workspace_id == membership.workspace_id,
    ))
    if agreement is None:
        raise HTTPException(status_code=404, detail="Agreement not found.")
    obligations = list(db.scalars(select(Obligation).where(Obligation.agreement_id == agreement.id).order_by(Obligation.created_at)))
    result = []
    for obligation in obligations:
        revision = db.scalar(select(ObligationRevision).where(
            ObligationRevision.obligation_id == obligation.id,
            ObligationRevision.status == "approved",
        ).order_by(ObligationRevision.revision_number.desc()).limit(1))
        if not revision:
            continue
        evidence = list(db.scalars(select(Evidence).where(Evidence.obligation_revision_id == revision.id)))
        result.append({
            "id": obligation.id,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "canonical_payload": revision.canonical_payload,
            "evidence": [{"page_number": item.page_number, "quote": item.quote, "source_section": item.source_section} for item in evidence],
        })
    return result
