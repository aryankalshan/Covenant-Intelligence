from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_dev_membership, get_db, require_roles
from app.modules.agreements.models import Agreement, AgreementVersion, DocumentPage, UserMembership, new_id, utcnow
from app.modules.amendments.models import AmendmentComparison, ComparisonDecision, ComparisonItem
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import record_audit
from app.modules.extraction.definitions import normalize_contract_text
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision
from app.modules.extraction.persistence import save_approved_revision_with_evidence
from app.modules.monitoring.models import MONITORING_STATUSES, MonitoringPeriod, MonitoringUpdate
from app.modules.review.models import ReviewDecision
from app.modules.review.service import validate_approved_obligation

router = APIRouter(prefix="/api/v1")


class ReviewDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approved", "corrected", "rejected", "needs_information"]
    comment: str | None = Field(default=None, max_length=3000)
    corrected_obligation: CanonicalObligation | None = None


class MonitoringPeriodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_label: str = Field(min_length=1, max_length=100)
    fiscal_year_end: date | None = None
    period_start: date
    period_end: date
    due_date: date | None = None
    deadline_rule: str | None = Field(default=None, max_length=2000)


class MonitoringUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["awaiting_setup", "upcoming", "due", "awaiting_evidence", "submitted", "reviewed", "not_assessed", "not_applicable"]
    note: str | None = Field(default=None, max_length=5000)
    supporting_reference: str | None = Field(default=None, max_length=500)
    evidence_received_at: date | None = None


class AmendmentComparisonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version_id: str
    amendment_version_id: str
    extraction_run_id: str


class ComparisonDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "rejected", "deferred"]
    comment: str | None = Field(default=None, max_length=3000)
    full_document_review_confirmed: bool = False


def _membership(db: Session, request: Request, handle: str | None):
    return current_dev_membership(db, handle, request.app.state.dev_identity_ids)


def _audit(db: Session, request: Request, membership: UserMembership, user_id: str, action: str, entity_type: str, entity_id: str, **summary):
    record_audit(db, workspace_id=membership.workspace_id, actor_user_id=user_id, action=action,
                 entity_type=entity_type, entity_id=entity_id,
                 request_id=request.headers.get("X-Request-ID"), summary=summary)


def _scoped_candidate(db: Session, candidate_id: str, workspace_id: str):
    candidate = db.scalar(select(ExtractionCandidate).join(ExtractionRun).join(AgreementVersion).join(Agreement).where(
        ExtractionCandidate.id == candidate_id, Agreement.workspace_id == workspace_id))
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    run = db.get(ExtractionRun, candidate.extraction_run_id)
    version = db.get(AgreementVersion, run.agreement_version_id)
    agreement = db.get(Agreement, version.agreement_id)
    return candidate, run, version, agreement


def _candidate_json(db: Session, candidate: ExtractionCandidate, *, include_pages=False):
    run = db.get(ExtractionRun, candidate.extraction_run_id)
    evidence = list(db.scalars(select(Evidence).where(Evidence.candidate_id == candidate.id).order_by(Evidence.page_number, Evidence.id)))
    result = {
        "id": candidate.id, "extraction_run_id": candidate.extraction_run_id,
        "status": candidate.status, "validation_status": candidate.validation_status,
        "extraction_origin": (
            "synthetic_demo" if run and run.provider == "synthetic_demo" else
            "mock_test" if run and run.provider == "mock" else
            "openrouter" if run and run.provider == "openrouter" else "provider"
        ),
        "validation_findings": candidate.validation_findings or [], "canonical_payload": candidate.canonical_payload,
        "evidence": [{"id": e.id, "page_number": e.page_number, "quote": e.quote, "source_section": e.source_section, "evidence_role": e.evidence_role} for e in evidence],
    }
    if include_pages:
        pages = {p.page_number: p for p in db.scalars(select(DocumentPage).where(DocumentPage.agreement_version_id == evidence[0].agreement_version_id))} if evidence else {}
        result["source_version_id"] = evidence[0].agreement_version_id if evidence else None
        result["source_pages"] = [{"page_number": number, "text": pages[number].text} for number in sorted({e.page_number for e in evidence}) if number in pages]
    return result


@router.get("/review/candidates")
def review_queue(request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    terminal = exists(select(ReviewDecision.id).where(
        ReviewDecision.candidate_id == ExtractionCandidate.id,
        ReviewDecision.decision.in_(["approved", "corrected", "rejected"]),
    ))
    rows = db.scalars(select(ExtractionCandidate).join(ExtractionRun).join(AgreementVersion).join(Agreement).where(
        Agreement.workspace_id == membership.workspace_id, ~terminal
    ).order_by(ExtractionCandidate.created_at))
    return [{**_candidate_json(db, row), "agreement_id": db.get(AgreementVersion, db.get(ExtractionRun, row.extraction_run_id).agreement_version_id).agreement_id} for row in rows]


@router.get("/review/candidates/{candidate_id}")
def review_candidate(candidate_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    candidate, run, version, agreement = _scoped_candidate(db, candidate_id, membership.workspace_id)
    result = _candidate_json(db, candidate, include_pages=True)
    result["agreement"] = {"id": agreement.id, "name": agreement.name, "version_id": version.id, "version_label": version.version_label}
    result["decisions"] = [{"decision": d.decision, "comment": d.comment, "created_at": d.created_at.isoformat()} for d in db.scalars(select(ReviewDecision).where(ReviewDecision.candidate_id == candidate.id).order_by(ReviewDecision.created_at))]
    return result


@router.post("/candidates/{candidate_id}/review-decisions", status_code=201)
def decide_candidate(candidate_id: str, body: ReviewDecisionIn, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = _membership(db, request, x_dev_user)
    require_roles(membership, {"admin", "reviewer"})
    candidate, run, version, agreement = _scoped_candidate(db, candidate_id, membership.workspace_id)
    prior = db.scalar(select(ReviewDecision).where(ReviewDecision.candidate_id == candidate.id).order_by(ReviewDecision.created_at.desc()).limit(1))
    if prior and prior.decision in {"approved", "corrected", "rejected"}:
        raise HTTPException(status_code=409, detail="This candidate already has a final review decision.")
    if body.action == "corrected" and body.corrected_obligation is None:
        raise HTTPException(status_code=422, detail="Corrected decisions require a complete canonical obligation replacement.")
    if body.action != "corrected" and body.corrected_obligation is not None:
        raise HTTPException(status_code=422, detail="corrected_obligation is accepted only for a corrected decision.")
    payload = (body.corrected_obligation or CanonicalObligation.model_validate(candidate.canonical_payload)).model_dump(mode="json") if body.action in {"approved", "corrected"} else None
    if payload is not None:
        canonical, findings = validate_approved_obligation(db, version, payload)
        if findings:
            raise HTTPException(status_code=422, detail={"message": "The obligation must be fully validated before approval.", "findings": findings})
        if (candidate.validation_findings or candidate.canonical_payload.get("uncertainty_reasons")) and not (body.comment or "").strip():
            raise HTTPException(status_code=422, detail="A reviewer explanation is required when resolving extraction uncertainty.")
        payload = canonical.model_dump(mode="json")
    decision = ReviewDecision(candidate_id=candidate.id, reviewer_id=user.id, decision=body.action, comment=body.comment,
                              supersedes_decision_id=prior.id if prior else None)
    db.add(decision); db.flush()
    revision = None
    if body.action in {"approved", "corrected"}:
        obligation = Obligation(agreement_id=agreement.id, lifecycle_status="active", created_by=user.id)
        db.add(obligation); db.flush()
        revision = save_approved_revision_with_evidence(db, obligation, version, payload, approved_by=user.id,
                                                         origin_candidate_id=candidate.id, review_decision_id=decision.id)
        obligation.current_revision_id = revision.id
    _audit(db, request, membership, user.id, f"candidate_{body.action}", "extraction_candidate", candidate.id, decision=body.action)
    if revision:
        _audit(db, request, membership, user.id, "obligation_revision_approved", "obligation_revision", revision.id, status="approved")
    db.commit()
    return {"decision_id": decision.id, "candidate_id": candidate.id, "decision": decision.decision,
            "obligation_id": revision.obligation_id if revision else None, "revision_id": revision.id if revision else None}


def _revision_detail(db: Session, revision: ObligationRevision):
    evidence = list(db.scalars(select(Evidence).where(Evidence.obligation_revision_id == revision.id).order_by(Evidence.page_number)))
    return {"id": revision.id, "obligation_id": revision.obligation_id, "revision_number": revision.revision_number,
            "status": revision.status, "canonical_payload": revision.canonical_payload,
            "approved_by": revision.approved_by, "approved_at": revision.approved_at.isoformat(),
            "origin_candidate_id": revision.origin_candidate_id,
            "evidence": [{"agreement_version_id": e.agreement_version_id, "page_number": e.page_number, "quote": e.quote, "source_section": e.source_section, "evidence_role": e.evidence_role} for e in evidence]}


@router.get("/obligations")
def obligation_register(request: Request, agreement_id: str | None = None, category: str | None = None,
                        search: str | None = None, sort: Literal["name", "category", "deadline"] = "name",
                        db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    query = select(Obligation).join(Agreement).where(Agreement.workspace_id == membership.workspace_id, Obligation.current_revision_id.is_not(None))
    if agreement_id:
        query = query.where(Agreement.id == agreement_id)
    if category:
        query = query.join(ObligationRevision, Obligation.current_revision_id == ObligationRevision.id).where(ObligationRevision.canonical_payload["obligation_category"].as_string() == category)
    obligations = list(db.scalars(query.order_by(Obligation.created_at.desc())))
    result = []
    for obligation in obligations:
        revision = db.get(ObligationRevision, obligation.current_revision_id)
        agreement = db.get(Agreement, obligation.agreement_id)
        payload = revision.canonical_payload
        if search and search.casefold() not in (payload.get("obligation_description", "") + " " + agreement.name).casefold():
            continue
        result.append({"id": obligation.id, "agreement_id": agreement.id, "agreement_name": agreement.name,
                       "lifecycle_status": obligation.lifecycle_status, "current_revision_id": revision.id,
                       "revision_number": revision.revision_number, "approved_at": revision.approved_at.isoformat(),
                       "canonical_payload": payload})
    key_map = {"name": lambda row: row["canonical_payload"].get("obligation_description", "").casefold(),
               "category": lambda row: row["canonical_payload"].get("obligation_category", ""),
               "deadline": lambda row: row["canonical_payload"].get("reporting_deadline") or row["canonical_payload"].get("deadline_calculation_rule") or "~"}
    return sorted(result, key=key_map[sort])


@router.get("/obligations/{obligation_id}")
def obligation_detail(obligation_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    obligation = db.scalar(select(Obligation).join(Agreement).where(Obligation.id == obligation_id, Agreement.workspace_id == membership.workspace_id))
    if not obligation:
        raise HTTPException(status_code=404, detail="Obligation not found.")
    revision = db.get(ObligationRevision, obligation.current_revision_id) if obligation.current_revision_id else None
    return {"id": obligation.id, "agreement_id": obligation.agreement_id, "lifecycle_status": obligation.lifecycle_status,
            "current": _revision_detail(db, revision) if revision else None}


@router.get("/obligations/{obligation_id}/revisions")
def obligation_revisions(obligation_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    obligation = db.scalar(select(Obligation).join(Agreement).where(Obligation.id == obligation_id, Agreement.workspace_id == membership.workspace_id))
    if not obligation:
        raise HTTPException(status_code=404, detail="Obligation not found.")
    rows = db.scalars(select(ObligationRevision).where(ObligationRevision.obligation_id == obligation.id).order_by(ObligationRevision.revision_number.desc()))
    return [_revision_detail(db, row) for row in rows]


def _is_overdue(period: MonitoringPeriod, today: date | None = None) -> bool:
    return bool(period.due_date and period.due_date < (today or date.today()) and period.status in {"awaiting_setup", "upcoming", "due", "awaiting_evidence"})


_DEADLINE_RULE = re.compile(r"^\s*within\s+(\d+)\s+(?:calendar\s+)?days?\s+after\s+(?:each\s+)?(fiscal year[- ]end|fiscal quarter[- ]end|quarter[- ]end|period[- ]end)\s*[.]?\s*$", re.I)


def calculate_clear_deadline(rule: str | None, *, fiscal_year_end: date | None, period_end: date) -> date | None:
    if not rule or re.search(r"business days|banking days|following business day", rule, re.I):
        return None
    match = _DEADLINE_RULE.match(rule)
    if not match:
        return None
    anchor_name = match.group(2).casefold()
    anchor = fiscal_year_end if "fiscal year" in anchor_name else period_end
    if anchor is None:
        return None
    return anchor + timedelta(days=int(match.group(1)))


def _monitoring_detail(db: Session, period: MonitoringPeriod, today: date | None = None):
    updates = list(db.scalars(select(MonitoringUpdate).where(MonitoringUpdate.monitoring_period_id == period.id).order_by(MonitoringUpdate.recorded_at.desc())))
    return {"id": period.id, "obligation_id": period.obligation_id, "obligation_revision_id": period.obligation_revision_id,
            "period_label": period.period_label, "fiscal_year_end": period.fiscal_year_end.isoformat() if period.fiscal_year_end else None,
            "period_start": period.period_start.isoformat(), "period_end": period.period_end.isoformat(),
            "due_date": period.due_date.isoformat() if period.due_date else None, "deadline_rule": period.deadline_rule,
            "status": period.status, "is_overdue": _is_overdue(period, today),
            "updates": [{"id": u.id, "status": u.status, "note": u.note, "supporting_reference": u.supporting_reference,
                         "evidence_received_at": u.evidence_received_at.isoformat() if u.evidence_received_at else None,
                         "recorded_by": u.recorded_by, "recorded_at": u.recorded_at.isoformat()} for u in updates]}


@router.get("/monitoring-periods")
def list_monitoring_periods(request: Request, agreement_id: str | None = None, status: str | None = None,
                            period_label: str | None = None, overdue: bool | None = None,
                            db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    query = select(MonitoringPeriod).join(Obligation).join(Agreement).where(Agreement.workspace_id == membership.workspace_id)
    if agreement_id: query = query.where(Agreement.id == agreement_id)
    if status:
        if status == "overdue":
            query = query.where(MonitoringPeriod.due_date < date.today(), MonitoringPeriod.status.in_(["awaiting_setup", "upcoming", "due", "awaiting_evidence"]))
        elif status in MONITORING_STATUSES: query = query.where(MonitoringPeriod.status == status)
        else: raise HTTPException(status_code=422, detail="Unsupported monitoring status.")
    if period_label: query = query.where(MonitoringPeriod.period_label == period_label)
    rows = list(db.scalars(query.order_by(MonitoringPeriod.due_date, MonitoringPeriod.period_start)))
    return [row for row in (_monitoring_detail(db, item) for item in rows) if overdue is None or row["is_overdue"] == overdue]


@router.post("/obligations/{obligation_id}/monitoring-periods", status_code=201)
def create_monitoring_period(obligation_id: str, body: MonitoringPeriodIn, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = _membership(db, request, x_dev_user)
    require_roles(membership, {"admin", "reviewer", "contributor"})
    obligation = db.scalar(select(Obligation).join(Agreement).where(Obligation.id == obligation_id, Agreement.workspace_id == membership.workspace_id))
    if not obligation or not obligation.current_revision_id or obligation.lifecycle_status != "active":
        raise HTTPException(status_code=404, detail="Active approved obligation not found.")
    if body.period_end < body.period_start:
        raise HTTPException(status_code=422, detail="period_end must be on or after period_start.")
    revision = db.get(ObligationRevision, obligation.current_revision_id)
    rule = body.deadline_rule or revision.canonical_payload.get("deadline_calculation_rule") or revision.canonical_payload.get("reporting_deadline")
    due_date = body.due_date or calculate_clear_deadline(rule, fiscal_year_end=body.fiscal_year_end, period_end=body.period_end)
    duplicate = db.scalar(select(MonitoringPeriod.id).where(MonitoringPeriod.obligation_id == obligation.id,
        MonitoringPeriod.obligation_revision_id == revision.id, MonitoringPeriod.period_label == body.period_label))
    if duplicate:
        raise HTTPException(status_code=409, detail="This obligation period is already initialized.")
    period = MonitoringPeriod(obligation_id=obligation.id, obligation_revision_id=revision.id, period_label=body.period_label,
        fiscal_year_end=body.fiscal_year_end, period_start=body.period_start, period_end=body.period_end,
        due_date=due_date, deadline_rule=rule, status="upcoming" if due_date else "awaiting_setup", created_by=user.id)
    db.add(period); db.flush()
    _audit(db, request, membership, user.id, "monitoring_period_created", "monitoring_period", period.id, period_label=period.period_label)
    db.commit(); db.refresh(period)
    result = _monitoring_detail(db, period)
    result["deadline_resolution"] = "user_configured" if body.due_date else ("calculated" if due_date else "needs_configuration")
    return result


@router.get("/monitoring-periods/{period_id}")
def get_monitoring_period(period_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    period = db.scalar(select(MonitoringPeriod).join(Obligation).join(Agreement).where(MonitoringPeriod.id == period_id, Agreement.workspace_id == membership.workspace_id))
    if not period: raise HTTPException(status_code=404, detail="Monitoring period not found.")
    return _monitoring_detail(db, period)


@router.post("/monitoring-periods/{period_id}/updates", status_code=201)
def update_monitoring_period(period_id: str, body: MonitoringUpdateIn, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = _membership(db, request, x_dev_user)
    if membership.role == "contributor":
        require_roles(membership, {"contributor"})
        contributor_statuses = {"awaiting_setup", "upcoming", "due", "awaiting_evidence", "submitted"}
        if body.status not in contributor_statuses:
            raise HTTPException(status_code=403, detail="Contributors may update reporting progress and submit evidence, but cannot record assessment decisions.")
    else:
        require_roles(membership, {"admin", "reviewer"})
    period = db.scalar(select(MonitoringPeriod).join(Obligation).join(Agreement).where(MonitoringPeriod.id == period_id, Agreement.workspace_id == membership.workspace_id))
    if not period: raise HTTPException(status_code=404, detail="Monitoring period not found.")
    update = MonitoringUpdate(monitoring_period_id=period.id, status=body.status, note=body.note,
        supporting_reference=body.supporting_reference, evidence_received_at=body.evidence_received_at, recorded_by=user.id)
    db.add(update); period.status = body.status
    _audit(db, request, membership, user.id, "monitoring_updated", "monitoring_period", period.id, status=body.status)
    db.commit(); db.refresh(period)
    return _monitoring_detail(db, period)


def _payload_diff(old: dict, new: dict) -> dict:
    fields = ("obligation_category", "obligation_description", "source_wording", "threshold_value", "comparison_operator", "threshold_unit", "measurement_basis", "testing_frequency", "testing_period", "reporting_deadline", "deadline_calculation_rule", "conditions", "exceptions", "referenced_definitions", "cross_references")
    return {field: {"previous": old.get(field), "proposed": new.get(field)} for field in fields if old.get(field) != new.get(field)}


def _norm_name(payload: dict) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_contract_text(payload.get("obligation_description", "")).casefold()).strip()


@router.post("/agreements/{agreement_id}/amendment-comparisons", status_code=201)
def create_amendment_comparison(agreement_id: str, body: AmendmentComparisonIn, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = _membership(db, request, x_dev_user)
    require_roles(membership, {"admin", "contributor"})
    agreement = db.scalar(select(Agreement).where(Agreement.id == agreement_id, Agreement.workspace_id == membership.workspace_id))
    if not agreement: raise HTTPException(status_code=404, detail="Agreement not found.")
    base = db.scalar(select(AgreementVersion).where(AgreementVersion.id == body.base_version_id, AgreementVersion.agreement_id == agreement.id))
    amended = db.scalar(select(AgreementVersion).where(AgreementVersion.id == body.amendment_version_id, AgreementVersion.agreement_id == agreement.id))
    run = db.get(ExtractionRun, body.extraction_run_id)
    if not base or not amended or base.id == amended.id: raise HTTPException(status_code=422, detail="Both versions must be distinct versions of the selected agreement.")
    if not run or run.agreement_version_id != amended.id or run.status not in {"succeeded", "partial"}:
        raise HTTPException(status_code=409, detail="A completed extraction run for the amendment version is required.")
    amendment_pages = list(db.scalars(select(DocumentPage).where(
        DocumentPage.agreement_version_id == amended.id).order_by(DocumentPage.page_number)))
    page_count = amended.page_count or 0
    pages_with_text = sum(bool(page.text.strip()) for page in amendment_pages)
    coverage_details = {
        "run_status": run.status,
        "chunk_count": run.chunk_count,
        "processed_chunk_count": run.processed_chunk_count,
        "unprocessed_chunk_count": run.unprocessed_chunk_count,
        "screened_out_chunk_count": run.screened_out_chunk_count,
        "document_page_count": page_count,
        "extracted_page_count": len(amendment_pages),
        "pages_with_text": pages_with_text,
    }
    coverage_complete = bool(
        run.status == "succeeded"
        and run.chunk_count > 0
        and run.processed_chunk_count == run.chunk_count
        and run.unprocessed_chunk_count == 0
        and run.screened_out_chunk_count == 0
        and page_count > 0
        and len(amendment_pages) == page_count
        and pages_with_text == page_count
    )
    coverage_details["complete"] = coverage_complete
    comparison = AmendmentComparison(agreement_id=agreement.id, base_version_id=base.id, amendment_version_id=amended.id,
        extraction_run_id=run.id, status="running", created_by=user.id,
        extraction_coverage_complete=coverage_complete, coverage_details=coverage_details)
    db.add(comparison); db.flush()
    old_pairs = []
    base_revision_ids = select(Evidence.obligation_revision_id).where(Evidence.agreement_version_id == base.id, Evidence.obligation_revision_id.is_not(None))
    for obligation in db.scalars(select(Obligation).where(Obligation.agreement_id == agreement.id,
        Obligation.current_revision_id.is_not(None), Obligation.lifecycle_status == "active",
        Obligation.current_revision_id.in_(base_revision_ids))):
        rev = db.get(ObligationRevision, obligation.current_revision_id)
        old_pairs.append((obligation, rev, rev.canonical_payload))
    terminal_candidate_review = exists(select(ReviewDecision.id).where(
        ReviewDecision.candidate_id == ExtractionCandidate.id,
        ReviewDecision.decision.in_(["approved", "corrected", "rejected"]),
    ))
    candidates = list(db.scalars(select(ExtractionCandidate).where(
        ExtractionCandidate.extraction_run_id == run.id, ~terminal_candidate_review,
    )))
    remaining_old = list(old_pairs); remaining_new = list(candidates); pairs = []
    for old in old_pairs:
        match = next((candidate for candidate in remaining_new if candidate.canonical_payload.get("obligation_category") == old[2].get("obligation_category") and _norm_name(candidate.canonical_payload) == _norm_name(old[2])), None)
        if match:
            pairs.append((old, match, 1.0, "exact_category_and_name")); remaining_new.remove(match); remaining_old.remove(old)
    for old in list(remaining_old):
        scored = [(SequenceMatcher(None, _norm_name(old[2]), _norm_name(candidate.canonical_payload)).ratio(), candidate)
                  for candidate in remaining_new if candidate.canonical_payload.get("obligation_category") == old[2].get("obligation_category")]
        if scored:
            score, match = max(scored, key=lambda item: item[0])
            if score >= 0.66:
                pairs.append((old, match, score, "similar_category_and_name_requires_human_confirmation")); remaining_new.remove(match); remaining_old.remove(old)
    items = []
    for old, candidate, score, rationale in pairs:
        changes = _payload_diff(old[2], candidate.canonical_payload)
        if changes:
            kind = "possible_match" if score < 1 else "changed"
            items.append(ComparisonItem(comparison_id=comparison.id, change_type=kind, prior_obligation_revision_id=old[1].id,
                candidate_id=candidate.id, proposed_changes=changes, rationale=rationale, similarity=score))
    for old in remaining_old:
        if coverage_complete:
            change_type = "removed"
            rationale = "No deterministic match was found in a complete extraction; this is only a proposal and requires full-document reviewer confirmation."
            proposed_changes = {"lifecycle_status": {"previous": "active", "proposed": "superseded"}}
        else:
            change_type = "unresolved"
            rationale = "No candidate match was found, but extraction/document coverage is incomplete. This does not establish removal; review the full amendment before deciding."
            proposed_changes = {"possible_removal": {"previous": "active", "proposed": "not_found_in_extraction"}, "extraction_coverage": coverage_details}
        items.append(ComparisonItem(comparison_id=comparison.id, change_type=change_type, prior_obligation_revision_id=old[1].id,
            proposed_changes=proposed_changes, rationale=rationale))
    for candidate in remaining_new:
        items.append(ComparisonItem(comparison_id=comparison.id, change_type="added", candidate_id=candidate.id,
            proposed_changes={"canonical_payload": {"previous": None, "proposed": candidate.canonical_payload}}, rationale="No prior approved obligation matched this candidate."))
    db.add_all(items); comparison.status = "ready_for_review"; comparison.completed_at = utcnow()
    _audit(db, request, membership, user.id, "amendment_comparison_created", "amendment_comparison", comparison.id, count=len(items), status="ready_for_review")
    db.commit()
    return {"id": comparison.id, "status": comparison.status, "base_version_id": base.id, "amendment_version_id": amended.id,
            "coverage": coverage_details, "items": [_comparison_item_json(db, item) for item in items]}


def _comparison_item_json(db: Session, item: ComparisonItem):
    result = {"id": item.id, "change_type": item.change_type, "prior_obligation_revision_id": item.prior_obligation_revision_id,
            "candidate_id": item.candidate_id, "proposed_changes": item.proposed_changes, "rationale": item.rationale,
            "similarity": item.similarity, "status": item.status}
    comparison = db.get(AmendmentComparison, item.comparison_id)
    result["extraction_coverage"] = comparison.coverage_details
    result["full_document_review_required"] = item.change_type in {"removed", "unresolved"} and item.prior_obligation_revision_id is not None
    if item.prior_obligation_revision_id:
        revision = db.get(ObligationRevision, item.prior_obligation_revision_id)
        evidence = db.scalars(select(Evidence).where(Evidence.obligation_revision_id == revision.id).order_by(Evidence.page_number))
        amendment = db.get(AgreementVersion, comparison.amendment_version_id)
        result["prior_obligation"] = {
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "canonical_payload": revision.canonical_payload,
            "evidence": [{"agreement_version_id": row.agreement_version_id, "page_number": row.page_number,
                          "quote": row.quote, "source_section": row.source_section, "evidence_role": row.evidence_role}
                         for row in evidence],
        }
        result["amendment_version"] = {
            "id": amendment.id, "version_label": amendment.version_label, "page_count": amendment.page_count,
            "sha256": amendment.sha256,
        }
    return result


@router.get("/agreements/{agreement_id}/amendment-comparisons")
def list_amendment_comparisons(agreement_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    agreement = db.scalar(select(Agreement).where(Agreement.id == agreement_id, Agreement.workspace_id == membership.workspace_id))
    if not agreement: raise HTTPException(status_code=404, detail="Agreement not found.")
    comparisons = list(db.scalars(select(AmendmentComparison).where(AmendmentComparison.agreement_id == agreement.id).order_by(AmendmentComparison.created_at.desc())))
    return [{"id": c.id, "status": c.status, "base_version_id": c.base_version_id, "amendment_version_id": c.amendment_version_id,
            "coverage": c.coverage_details,
            "items": [_comparison_item_json(db, item) for item in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == c.id))]} for c in comparisons]


@router.get("/comparison-items/{item_id}/removal-review")
def comparison_removal_review(item_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    item = db.scalar(select(ComparisonItem).join(AmendmentComparison).join(Agreement).where(
        ComparisonItem.id == item_id, Agreement.workspace_id == membership.workspace_id))
    if not item or not item.prior_obligation_revision_id or item.change_type not in {"removed", "unresolved"}:
        raise HTTPException(status_code=404, detail="Removal review material not found.")
    comparison = db.get(AmendmentComparison, item.comparison_id)
    version = db.get(AgreementVersion, comparison.amendment_version_id)
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.agreement_version_id == version.id).order_by(DocumentPage.page_number)))
    return {
        "item_id": item.id,
        "amendment_version": {"id": version.id, "version_label": version.version_label, "original_filename": version.original_filename,
                              "sha256": version.sha256, "page_count": version.page_count},
        "extraction_coverage": comparison.coverage_details,
        "pages": [{"page_number": page.page_number, "text": page.text, "warnings": page.warnings} for page in pages],
    }


@router.post("/comparison-items/{item_id}/decisions", status_code=201)
def decide_comparison_item(item_id: str, body: ComparisonDecisionIn, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = _membership(db, request, x_dev_user)
    require_roles(membership, {"admin", "reviewer"})
    item = db.scalar(select(ComparisonItem).join(AmendmentComparison).join(Agreement).where(
        ComparisonItem.id == item_id, Agreement.workspace_id == membership.workspace_id))
    if not item: raise HTTPException(status_code=404, detail="Comparison item not found.")
    if item.status != "pending": raise HTTPException(status_code=409, detail="Comparison item already has a decision.")
    comparison = db.get(AmendmentComparison, item.comparison_id)
    removal_review = item.change_type in {"removed", "unresolved"} and item.prior_obligation_revision_id is not None
    if body.full_document_review_confirmed and (body.decision != "accepted" or not removal_review):
        raise HTTPException(status_code=422, detail="Full-document confirmation applies only when accepting a removal proposal.")
    if body.decision == "accepted" and removal_review:
        if not body.full_document_review_confirmed:
            raise HTTPException(status_code=422, detail="Confirm that you reviewed the complete amendment before accepting this possible removal.")
        if not (body.comment or "").strip():
            raise HTTPException(status_code=422, detail="A reviewer explanation is required when accepting a proposed removal.")
    decision = ComparisonDecision(comparison_item_id=item.id, reviewer_id=user.id, decision=body.decision,
                                  comment=body.comment, full_document_review_confirmed=body.full_document_review_confirmed)
    db.add(decision)
    if body.decision == "accepted":
        if removal_review:
            prior = db.get(ObligationRevision, item.prior_obligation_revision_id)
            obligation = db.get(Obligation, prior.obligation_id)
            obligation.lifecycle_status = "superseded"
        elif item.candidate_id:
            candidate = db.get(ExtractionCandidate, item.candidate_id)
            run = db.get(ExtractionRun, candidate.extraction_run_id)
            version = db.get(AgreementVersion, run.agreement_version_id)
            payload, findings = validate_approved_obligation(db, version, candidate.canonical_payload)
            if findings: raise HTTPException(status_code=422, detail={"message": "Amendment candidate cannot be accepted until its full payload is verified.", "findings": findings})
            if item.prior_obligation_revision_id:
                prior = db.get(ObligationRevision, item.prior_obligation_revision_id)
                obligation = db.get(Obligation, prior.obligation_id)
                prior.status = "superseded"
            else:
                obligation = Obligation(agreement_id=comparison.agreement_id, lifecycle_status="active", created_by=user.id)
                db.add(obligation); db.flush()
            revision = save_approved_revision_with_evidence(db, obligation, version, payload.model_dump(mode="json"),
                approved_by=user.id, origin_candidate_id=candidate.id)
            obligation.current_revision_id = revision.id
        else:
            raise HTTPException(status_code=422, detail="This proposed change cannot be accepted without source evidence.")
    item.status = body.decision
    db.flush()
    pending = db.scalar(select(func.count()).select_from(ComparisonItem).where(ComparisonItem.comparison_id == comparison.id, ComparisonItem.status == "pending")) or 0
    if not pending: comparison.status = "completed"
    _audit(db, request, membership, user.id, f"amendment_{body.decision}", "comparison_item", item.id, decision=body.decision, change_type=item.change_type)
    db.commit()
    return {"item_id": item.id, "status": item.status, "comparison_status": comparison.status}


@router.get("/audit-events")
def list_audit_events(request: Request, action: str | None = None, entity_type: str | None = None, limit: int = Query(100, ge=1, le=500),
                      db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = _membership(db, request, x_dev_user)
    query = select(AuditEvent).where(AuditEvent.workspace_id == membership.workspace_id)
    if action: query = query.where(AuditEvent.action == action)
    if entity_type: query = query.where(AuditEvent.entity_type == entity_type)
    events = db.scalars(query.order_by(AuditEvent.occurred_at.desc()).limit(limit))
    return [{"id": e.id, "actor_user_id": e.actor_user_id, "action": e.action, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "occurred_at": e.occurred_at.isoformat(), "request_id": e.request_id, "summary": e.summary} for e in events]
