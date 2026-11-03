from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agreements.models import AgreementVersion, DocumentPage, new_id
from app.modules.extraction.models import ExtractionCandidate
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.extraction.definitions import normalize_contract_text, verified_quote
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision


def _validated_payload(db: Session, version: AgreementVersion, payload: dict) -> CanonicalObligation:
    canonical = CanonicalObligation.model_validate(payload)
    for item in canonical.supporting_evidence:
        page = db.scalar(select(DocumentPage).where(
            DocumentPage.agreement_version_id == version.id,
            DocumentPage.page_number == item.source_page,
        ))
        if page is None:
            raise ValueError(f"Evidence references missing page {item.source_page}.")
        if not verified_quote(item.quote, page.text):
            raise ValueError(f"Evidence quote does not match extracted page {item.source_page} text.")
    return canonical


def _evidence_role(payload: CanonicalObligation, quote: str) -> str:
    normalized = normalize_contract_text(quote)
    if any(definition.definition_text and normalize_contract_text(definition.definition_text) == normalized for definition in payload.referenced_definitions or []):
        return "definition"
    if any(reference.target_description and normalize_contract_text(reference.target_description) == normalized for reference in payload.cross_references or []):
        return "cross_reference"
    return "operative_clause"


def _evidence_rows(version_id: str, payload: CanonicalObligation, *, candidate_id: str | None = None, revision_id: str | None = None):
    return [Evidence(
        agreement_version_id=version_id,
        page_number=item.source_page,
        quote=item.quote,
        source_section=item.source_section,
        evidence_role=_evidence_role(payload, item.quote),
        candidate_id=candidate_id,
        obligation_revision_id=revision_id,
    ) for item in payload.supporting_evidence]


def save_candidate_with_evidence(
    db: Session,
    extraction_run_id: str,
    version: AgreementVersion,
    payload: dict,
    *,
    status: str = "awaiting_review",
    validation_status: str = "valid",
    validation_findings: list[dict] | None = None,
) -> ExtractionCandidate:
    """Persist immutable full canonical payload and normalized evidence rows atomically."""
    canonical = _validated_payload(db, version, payload)
    candidate = ExtractionCandidate(
        id=new_id(), extraction_run_id=extraction_run_id,
        category=canonical.obligation_category,
        status=status,
        validation_status=validation_status,
        validation_findings=validation_findings or [],
        canonical_payload=canonical.model_dump(mode="json"),
    )
    with db.begin_nested():
        db.add(candidate)
        db.flush()
        db.add_all(_evidence_rows(version.id, canonical, candidate_id=candidate.id))
        db.flush()
    return candidate


def save_approved_revision_with_evidence(
    db: Session,
    obligation: Obligation,
    version: AgreementVersion,
    payload: dict,
    *,
    approved_by: str,
    origin_candidate_id: str | None = None,
    review_decision_id: str | None = None,
) -> ObligationRevision:
    """Persist the complete human-approved object and its relational citations atomically."""
    canonical = _validated_payload(db, version, payload)
    latest = db.scalar(select(ObligationRevision.revision_number).where(
        ObligationRevision.obligation_id == obligation.id,
    ).order_by(ObligationRevision.revision_number.desc()).limit(1)) or 0
    revision = ObligationRevision(
        id=new_id(), obligation_id=obligation.id, revision_number=latest + 1,
        canonical_payload=canonical.model_dump(mode="json"), status="approved",
        approved_by=approved_by, origin_candidate_id=origin_candidate_id,
        review_decision_id=review_decision_id,
    )
    with db.begin_nested():
        db.add(revision)
        db.flush()
        db.add_all(_evidence_rows(version.id, canonical, revision_id=revision.id))
        db.flush()
    return revision
