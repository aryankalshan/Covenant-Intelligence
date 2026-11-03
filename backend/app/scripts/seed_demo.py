"""Seed clearly marked synthetic demo agreements without deleting existing data.

Run after migrations from ``backend/`` with ``python -m app.scripts.seed_demo``.
This script never sends documents to an LLM provider.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pymupdf as fitz
from sqlalchemy import select

from app.core.config import DATABASE_URL, DEV_IDENTITIES, DEV_WORKSPACE_ID, STORAGE_DIR
from app.db.session import build_session_factory
from app.modules.agreements.models import (
    Agreement, AgreementVersion, DocumentPage, User, UserMembership, Workspace, new_id,
)
from app.modules.amendments.models import AmendmentComparison, ComparisonItem
from app.modules.audit.models import AuditEvent
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.monitoring.models import MonitoringPeriod, MonitoringUpdate
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision
from app.modules.review.models import ReviewDecision  # noqa: F401 — registers its FK table with Base.metadata


DEMO_PREFIX = "[SYNTHETIC DEMO]"


def _make_pdf(pages: list[str]) -> bytes:
    document = fitz.open()
    for page_text in pages:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(55, 55, 555, 780), page_text, fontsize=10, lineheight=1.35)
    output = document.tobytes()
    document.close()
    return output


def _clause_payload(
    *, category: str, description: str, wording: str, page: int, section: str,
    threshold: str | None = None, operator: str | None = None, unit: str | None = None,
    basis: str | None = None, frequency: str | None = None, period: str | None = None,
    deadline: str | None = None, deadline_rule: str | None = None,
    conditions: list[str] | None = None, exceptions: list[str] | None = None,
    definition: tuple[str, str] | None = None,
    cross_reference: tuple[str, str] | None = None,
) -> dict:
    evidence = [{"quote": wording, "source_page": page, "source_section": section}]
    definitions = None
    if definition:
        term, text = definition
        definitions = [{"term": term, "definition_text": text, "source_page": page, "source_section": section}]
        if text not in wording:
            evidence.append({"quote": text, "source_page": page, "source_section": section})
    cross_references = None
    if cross_reference:
        reference_text, target_text = cross_reference
        cross_references = [{"reference_text": reference_text, "target_description": target_text,
            "source_page": page, "source_section": section}]
        evidence.append({"quote": target_text, "source_page": page, "source_section": "Section 1.1"})
    return CanonicalObligation.model_validate({
        "obligation_category": category,
        "obligation_description": description,
        "source_wording": wording,
        "threshold_value": threshold,
        "comparison_operator": operator,
        "threshold_unit": unit,
        "measurement_basis": basis,
        "testing_frequency": frequency,
        "testing_period": period,
        "reporting_deadline": deadline,
        "deadline_calculation_rule": deadline_rule,
        "conditions": conditions,
        "exceptions": exceptions,
        "referenced_definitions": definitions,
        "cross_references": cross_references,
        "supporting_evidence": evidence,
        "uncertainty_reasons": [],
    }).model_dump(mode="json")


def _obligation_specs(borrower: str, *, amended: bool = False) -> list[dict]:
    leverage_value = "4.00" if amended else "3.50"
    leverage_wording = (
        f"Section 4.1. The Borrower shall not permit the Total Leverage Ratio as of any fiscal quarter end to exceed {leverage_value}:1.00."
    )
    return [
        _clause_payload(category="financial_covenant", description="Maximum Total Leverage Ratio", wording=leverage_wording,
            page=1, section="Section 4.1", threshold=leverage_value, operator="<=", unit="ratio", basis="Total Debt / EBITDA",
            frequency="quarterly", period="Each fiscal quarter end", conditions=["as of any fiscal quarter end"],
            definition=("Total Leverage Ratio", "Total Leverage Ratio means Total Debt divided by EBITDA.")),
        _clause_payload(category="financial_covenant", description="Minimum Interest Coverage Ratio",
            wording="Section 4.2. The Borrower shall maintain an Interest Coverage Ratio of not less than 2.50:1.00 for each Testing Period.",
            page=2, section="Section 4.2", threshold="2.50", operator=">=", unit="ratio", basis="EBITDA / Interest Expense",
            frequency="quarterly", period="Each Testing Period", definition=("Testing Period", "Testing Period means each period of four consecutive fiscal quarters.")),
        _clause_payload(category="financial_covenant", description="Minimum Liquidity Requirement",
            wording="Section 4.3. The Borrower shall maintain Liquidity of at least INR 5 crore at all times.",
            page=3, section="Section 4.3", threshold="5", operator=">=", unit="INR crore", basis="Unrestricted cash and available committed facility", frequency="continuous", period="At all times",
            conditions=["Committed undrawn facilities must be available for drawing"]),
        _clause_payload(category="reporting_obligation", description="Quarterly Financial Statements",
            wording="Section 5.1. Within 45 days after each fiscal quarter end, deliver unaudited quarterly financial statements for the Borrower and its subsidiaries.",
            page=4, section="Section 5.1", frequency="quarterly", period="Each fiscal quarter", deadline="Within 45 days after each fiscal quarter end", deadline_rule="Within 45 days after each fiscal quarter end"),
        _clause_payload(category="reporting_obligation", description="Annual Audited Financial Statements",
            wording="Section 5.2. Within 120 days after each fiscal year end, deliver audited consolidated annual financial statements.",
            page=5, section="Section 5.2", frequency="annually", period="Each fiscal year", deadline="Within 120 days after each fiscal year end", deadline_rule="Within 120 days after each fiscal year end"),
        _clause_payload(category="reporting_obligation", description="Quarterly Compliance Certificate",
            wording="Section 5.3. Together with each quarterly financial statement delivery, an authorised officer shall deliver a compliance certificate.",
            page=6, section="Section 5.3", frequency="quarterly", period="Each fiscal quarter", deadline="Together with each quarterly financial statement delivery", deadline_rule="Together with each quarterly financial statement delivery"),
        _clause_payload(category="negative_covenant", description="Capital Expenditure Limitation",
            wording="Section 6.1. The Borrower shall not permit aggregate capital expenditures to exceed INR 12 crore in any fiscal year, except for emergency repairs required to protect life or property.",
            page=7, section="Section 6.1", threshold="12", operator="<=", unit="INR crore per fiscal year", basis="Aggregate capital expenditures", frequency="annually", period="Each fiscal year",
            exceptions=["emergency repairs required to protect life or property"]),
        _clause_payload(category="negative_covenant", description="Additional Indebtedness Restriction",
            wording="Section 6.2. The Borrower shall not incur additional Indebtedness, except for Permitted Indebtedness described in Section 1.1.",
            page=8, section="Section 6.2", exceptions=["Permitted Indebtedness described in Section 1.1"],
            definition=("Indebtedness", "Indebtedness means borrowed money, finance leases and guarantees of borrowed money."),
            cross_reference=("Section 1.1", "Section 1.1. Permitted Indebtedness means indebtedness specifically permitted under this Agreement.")),
        _clause_payload(category="negative_covenant", description="Asset Sale Restriction",
            wording="Section 6.3. The Borrower shall not sell or dispose of material assets, except for obsolete equipment sold in the ordinary course of business.",
            page=9, section="Section 6.3", exceptions=["obsolete equipment sold in the ordinary course of business"]),
        _clause_payload(category="negative_covenant", description="Distribution Restriction",
            wording="Section 6.4. The Borrower shall not declare or pay distributions while a payment default is continuing or would result therefrom.",
            page=10, section="Section 6.4", conditions=["Restriction applies while a payment default is continuing or would result"]),
    ]


def _candidate_payload(description: str, wording: str, page: int, *, uncertainty: list[str] | None = None,
                       threshold: str | None = None, operator: str | None = None, unit: str | None = None,
                       category: str = "negative_covenant", definitions: list[dict] | None = None,
                       exceptions: list[str] | None = None) -> dict:
    return CanonicalObligation.model_validate({
        "obligation_category": category, "obligation_description": description,
        "source_wording": wording, "threshold_value": threshold, "comparison_operator": operator,
        "threshold_unit": unit, "measurement_basis": None, "testing_frequency": None,
        "testing_period": None, "reporting_deadline": None, "deadline_calculation_rule": None,
        "conditions": None, "exceptions": exceptions, "referenced_definitions": definitions,
        "cross_references": None,
        "supporting_evidence": [{"quote": wording, "source_page": page, "source_section": f"Section 6.{page}"}],
        "uncertainty_reasons": uncertainty or [],
    }).model_dump(mode="json")


def seed_demo_data(session_factory, storage_dir: Path) -> dict[str, int]:
    """Create/reuse synthetic demo rows; calling repeatedly is safe and additive."""
    storage_dir = Path(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with session_factory.begin() as db:
        workspace = db.get(Workspace, DEV_WORKSPACE_ID)
        if workspace is None:
            workspace = Workspace(id=DEV_WORKSPACE_ID, name="Covenant Intelligence Development")
            db.add(workspace)
        user_ids: dict[str, str] = {}
        for handle, spec in DEV_IDENTITIES.items():
            user_ids[handle] = spec["id"]
            if db.get(User, spec["id"]) is None:
                db.add(User(id=spec["id"], display_name=spec["name"]))
            if db.scalar(select(UserMembership).where(UserMembership.workspace_id == DEV_WORKSPACE_ID,
                                                       UserMembership.user_id == spec["id"])) is None:
                db.add(UserMembership(workspace_id=DEV_WORKSPACE_ID, user_id=spec["id"], role=spec["role"]))
        db.flush()

        borrower_names = ["Northstar Components Pvt Ltd", "Meridian Industrial Systems Pvt Ltd", "Apex Manufacturing Pvt Ltd"]
        agreements: dict[str, Agreement] = {}
        for borrower in borrower_names:
            name = f"{DEMO_PREFIX} {borrower} Credit Facility"
            agreement = db.scalar(select(Agreement).where(Agreement.workspace_id == DEV_WORKSPACE_ID, Agreement.name == name))
            if agreement is None:
                agreement = Agreement(workspace_id=DEV_WORKSPACE_ID, name=name,
                    counterparty="Fictional Lender: Example Development Finance Bank",
                    created_by=user_ids["contributor"])
                db.add(agreement); db.flush()
                db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                    action="demo_agreement_created", entity_type="agreement", entity_id=agreement.id,
                    summary={"status": "synthetic_demo"}))
            agreements[borrower] = agreement
        db.flush()

        versions: dict[tuple[str, str], AgreementVersion] = {}
        for borrower in borrower_names:
            labels = ["Synthetic Original"]
            if borrower == borrower_names[0]:
                labels.append("Synthetic Amendment 1")
            for label in labels:
                agreement = agreements[borrower]
                version = db.scalar(select(AgreementVersion).where(AgreementVersion.agreement_id == agreement.id,
                                                                     AgreementVersion.version_label == label))
                if version is None:
                    is_amendment = label == "Synthetic Amendment 1"
                    specs = _obligation_specs(borrower, amended=is_amendment)
                    page_texts: list[str]
                    if is_amendment:
                        page_texts = [
                            f"{DEMO_PREFIX}\nFirst Amendment to fictional Term Loan Facility for {borrower}.\nDated 1 January 2026.\nSection 4.1. The Borrower shall not permit the Total Leverage Ratio as of any fiscal quarter end to exceed 4.00:1.00.\nTotal Leverage Ratio means Total Debt divided by EBITDA.\nAll entities and provisions are synthetic."
                        ]
                    else:
                        page_texts = []
                        for spec in specs:
                            definition_lines = "\n".join(d["definition_text"] for d in spec["referenced_definitions"] or [])
                            target_lines = "\n".join(r["target_description"] for r in spec["cross_references"] or [])
                            page_texts.append(f"{DEMO_PREFIX}\nFictional Term Loan Facility for {borrower}.\nDated 15 January 2025.\n{spec['source_wording']}\n{definition_lines}\n{target_lines}\nAll entities and provisions are synthetic.")
                    pdf_bytes = _make_pdf(page_texts)
                    sha = hashlib.sha256(pdf_bytes).hexdigest()
                    storage_key = f"synthetic-demo-{agreement.id[:8]}-{len(versions)}-{sha[:12]}.pdf"
                    path = storage_dir / storage_key
                    if path.exists():
                        storage_key = f"synthetic-demo-{agreement.id[:8]}-{new_id()}-{sha[:12]}.pdf"
                        path = storage_dir / storage_key
                    path.write_bytes(pdf_bytes)
                    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
                    version = AgreementVersion(id=new_id(), agreement_id=agreement.id, version_label=label,
                        source_kind="synthetic", original_filename=f"{borrower.lower().replace(' ', '-')}-{label.lower().replace(' ', '-')}.pdf",
                        sha256=sha, storage_key=storage_key, mime_type="application/pdf", size_bytes=len(pdf_bytes),
                        page_count=len(pdf), status="processed", uploaded_by=user_ids["contributor"], processed_at=datetime.now(timezone.utc))
                    db.add(version); db.flush()
                    for index, page in enumerate(pdf, start=1):
                        text = page.get_text()
                        db.add(DocumentPage(agreement_version_id=version.id, page_number=index, text=text,
                            extraction_method="synthetic_demo_fixture", warnings="[]", text_sha256=hashlib.sha256(text.encode()).hexdigest()))
                    pdf.close()
                    db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                        action="demo_document_uploaded", entity_type="agreement_version", entity_id=version.id,
                        summary={"status": "synthetic_demo"}))
                    db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                        action="demo_document_processed", entity_type="agreement_version", entity_id=version.id,
                        summary={"status": "processed"}))
                versions[(borrower, label)] = version
        db.flush()

        manual_obligations: list[tuple[Agreement, AgreementVersion, dict]] = []
        borrower_specs = {
            borrower_names[0]: _obligation_specs(borrower_names[0])[:8],
            borrower_names[1]: [_obligation_specs(borrower_names[1])[1], _obligation_specs(borrower_names[1])[6], _obligation_specs(borrower_names[1])[8]],
            borrower_names[2]: [_obligation_specs(borrower_names[2])[2], _obligation_specs(borrower_names[2])[4], _obligation_specs(borrower_names[2])[9]],
        }
        for borrower, specs in borrower_specs.items():
            version = versions[(borrower, "Synthetic Original")]
            for payload in specs:
                exists_obligation = db.scalar(select(Obligation.id).join(Agreement).join(ObligationRevision, Obligation.current_revision_id == ObligationRevision.id)
                    .where(Agreement.id == agreements[borrower].id, ObligationRevision.canonical_payload["obligation_description"].as_string() == payload["obligation_description"]))
                if exists_obligation:
                    continue
                obligation = Obligation(agreement_id=agreements[borrower].id, lifecycle_status="active", created_by=user_ids["admin"])
                db.add(obligation); db.flush()
                revision = ObligationRevision(obligation_id=obligation.id, revision_number=1, canonical_payload=payload,
                    status="approved", approved_by=user_ids["reviewer"], approved_at=datetime.now(timezone.utc))
                db.add(revision); db.flush()
                obligation.current_revision_id = revision.id
                for citation in payload["supporting_evidence"]:
                    db.add(Evidence(agreement_version_id=version.id, page_number=citation["source_page"], quote=citation["quote"],
                        source_section=citation["source_section"], evidence_role="operative_clause", obligation_revision_id=revision.id))
                db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["reviewer"],
                    action="demo_obligation_approved", entity_type="obligation_revision", entity_id=revision.id,
                    summary={"status": "synthetic_demo"}))
                manual_obligations.append((agreements[borrower], version, payload))
        db.flush()

        # Candidates are explicitly synthetic fixtures and remain unreviewed.
        candidate_specs = [
            (borrower_names[0], "Synthetic Review Candidate — Leverage", _obligation_specs(borrower_names[0])[0], [], []),
            (borrower_names[0], "Synthetic Review Candidate — Reporting Deadline", _obligation_specs(borrower_names[0])[3], ["Confirm the period-end definition in the full agreement."], []),
            (borrower_names[0], "Synthetic Review Candidate — Additional Debt", _obligation_specs(borrower_names[0])[6], ["Confirm scope of the Permitted Indebtedness exception."], []),
            (borrower_names[1], "Synthetic Review Candidate — Asset Sale", _obligation_specs(borrower_names[1])[8], ["Check interaction with the referenced ordinary-course exception."], []),
            (borrower_names[2], "Synthetic Review Candidate — Liquidity", _obligation_specs(borrower_names[2])[2], [], [{"code": "threshold_requires_confirmation", "field": "threshold_value", "message": "Confirm this synthetic threshold before relying on it."}]),
        (borrower_names[2], "Synthetic Review Candidate — Annual Audited Statements", _obligation_specs(borrower_names[2])[4], [], []),
        ]
        runs_by_version: dict[str, ExtractionRun] = {}
        for borrower, description, original_payload, uncertainty, forced_findings in candidate_specs:
            version = versions[(borrower, "Synthetic Original")]
            run = runs_by_version.get(version.id)
            if run is None:
                run = db.scalar(select(ExtractionRun).where(ExtractionRun.agreement_version_id == version.id,
                    ExtractionRun.provider == "synthetic_demo"))
                if run is None:
                    run = ExtractionRun(agreement_version_id=version.id, status="succeeded", schema_version="1.1.0",
                        provider="synthetic_demo", model="not-used", prompt_version="synthetic-fixture-v1",
                        started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                        requested_by=user_ids["contributor"], chunk_count=1, processed_chunk_count=1,
                        candidate_count=0, requested_categories=["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"],
                        provider_metadata={"synthetic_demo": True, "llm_called": False})
                    db.add(run); db.flush()
                if db.scalar(select(AuditEvent.id).where(AuditEvent.entity_id == run.id,
                        AuditEvent.action == "demo_extraction_created")) is None:
                    db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                        action="demo_extraction_created", entity_type="extraction_run", entity_id=run.id,
                        summary={"status": "synthetic_demo"}))
                runs_by_version[version.id] = run
            existing = db.scalar(select(ExtractionCandidate.id).where(ExtractionCandidate.extraction_run_id == run.id,
                ExtractionCandidate.canonical_payload["obligation_description"].as_string() == description))
            if existing:
                continue
            payload = dict(original_payload)
            payload["obligation_description"] = description
            payload["uncertainty_reasons"] = uncertainty
            findings = forced_findings or ([{"code": "uncertainty_present", "field": "uncertainty_reasons"}] if uncertainty else [])
            candidate = ExtractionCandidate(extraction_run_id=run.id, category=payload["obligation_category"],
                status="awaiting_review", validation_status="needs_review" if findings else "valid",
                validation_findings=findings, canonical_payload=payload)
            db.add(candidate); db.flush()
            run.candidate_count = (run.candidate_count or 0) + 1
            for citation in payload["supporting_evidence"]:
                db.add(Evidence(agreement_version_id=version.id, page_number=citation["source_page"], quote=citation["quote"],
                    source_section=citation["source_section"], evidence_role="operative_clause", candidate_id=candidate.id))
            db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                action="demo_extraction_candidate_created", entity_type="extraction_candidate", entity_id=candidate.id,
                summary={"status": "synthetic_demo"}))

        # Candidate for an amendment proposal: this remains pending until a reviewer acts.
        northstar = borrower_names[0]
        original = versions[(northstar, "Synthetic Original")]
        amendment = versions[(northstar, "Synthetic Amendment 1")]
        leverage = _obligation_specs(northstar, amended=True)[0]
        amendment_run = db.scalar(select(ExtractionRun).where(ExtractionRun.agreement_version_id == amendment.id,
            ExtractionRun.provider == "synthetic_demo"))
        if amendment_run is None:
            amendment_run = ExtractionRun(agreement_version_id=amendment.id, status="succeeded", schema_version="1.1.0",
                provider="synthetic_demo", model="not-used", prompt_version="synthetic-fixture-v1",
                started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                requested_by=user_ids["contributor"], chunk_count=1, processed_chunk_count=1, candidate_count=0,
                requested_categories=["financial_covenant"], provider_metadata={"synthetic_demo": True, "llm_called": False})
            db.add(amendment_run); db.flush()
        if db.scalar(select(AuditEvent.id).where(AuditEvent.entity_id == amendment_run.id,
                AuditEvent.action == "demo_extraction_created")) is None:
            db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                action="demo_extraction_created", entity_type="extraction_run", entity_id=amendment_run.id,
                summary={"status": "synthetic_demo"}))
        amendment_candidate = db.scalar(select(ExtractionCandidate).where(
            ExtractionCandidate.extraction_run_id == amendment_run.id,
            ExtractionCandidate.canonical_payload["threshold_value"].as_string() == "4.00"))
        if amendment_candidate is None:
            amendment_candidate = ExtractionCandidate(extraction_run_id=amendment_run.id, category="financial_covenant",
                status="awaiting_review", validation_status="valid", validation_findings=[], canonical_payload=leverage)
            db.add(amendment_candidate); db.flush(); amendment_run.candidate_count = 1
            for citation in leverage["supporting_evidence"]:
                db.add(Evidence(agreement_version_id=amendment.id, page_number=citation["source_page"], quote=citation["quote"],
                    source_section=citation["source_section"], evidence_role="operative_clause", candidate_id=amendment_candidate.id))
        # Keep a separate, schema-valid review fixture so the reviewer can test amendment approval
        # without changing the original immutable candidate created by an earlier seed revision.
        reviewable_payload = dict(leverage)
        reviewable_payload["obligation_description"] = "Maximum Total Leverage Ratio — reviewable demo amendment"
        reviewable_payload["conditions"] = None
        reviewable_candidate = db.scalar(select(ExtractionCandidate).where(
            ExtractionCandidate.extraction_run_id == amendment_run.id,
            ExtractionCandidate.canonical_payload["obligation_description"].as_string() == reviewable_payload["obligation_description"]))
        if reviewable_candidate is None:
            reviewable_candidate = ExtractionCandidate(extraction_run_id=amendment_run.id, category="financial_covenant",
                status="awaiting_review", validation_status="valid", validation_findings=[], canonical_payload=reviewable_payload)
            db.add(reviewable_candidate); db.flush(); amendment_run.candidate_count = (amendment_run.candidate_count or 0) + 1
            for citation in reviewable_payload["supporting_evidence"]:
                db.add(Evidence(agreement_version_id=amendment.id, page_number=citation["source_page"], quote=citation["quote"],
                    source_section=citation["source_section"], evidence_role="operative_clause", candidate_id=reviewable_candidate.id))
        comparison = db.scalar(select(AmendmentComparison).where(AmendmentComparison.agreement_id == agreements[northstar].id,
            AmendmentComparison.base_version_id == original.id, AmendmentComparison.amendment_version_id == amendment.id))
        if comparison is None:
            comparison = AmendmentComparison(agreement_id=agreements[northstar].id, base_version_id=original.id,
                amendment_version_id=amendment.id, extraction_run_id=amendment_run.id, status="ready_for_review",
                created_by=user_ids["contributor"], completed_at=datetime.now(timezone.utc), algorithm_version="deterministic-v1",
                extraction_coverage_complete=True, coverage_details={"run_status": "succeeded", "chunk_count": 1,
                    "processed_chunk_count": 1, "unprocessed_chunk_count": 0, "screened_out_chunk_count": 0,
                    "document_page_count": 1, "extracted_page_count": 1, "pages_with_text": 1, "complete": True,
                    "synthetic_demo": True})
            db.add(comparison); db.flush()
            base_obligation = db.scalar(select(Obligation).join(ObligationRevision, Obligation.current_revision_id == ObligationRevision.id)
                .where(Obligation.agreement_id == agreements[northstar].id,
                       ObligationRevision.canonical_payload["obligation_description"].as_string() == "Maximum Total Leverage Ratio"))
        else:
            base_obligation = db.scalar(select(Obligation).join(ObligationRevision, Obligation.current_revision_id == ObligationRevision.id)
                .where(Obligation.agreement_id == agreements[northstar].id,
                       ObligationRevision.canonical_payload["obligation_description"].as_string() == "Maximum Total Leverage Ratio"))
        if base_obligation and db.scalar(select(ComparisonItem.id).where(ComparisonItem.comparison_id == comparison.id,
                ComparisonItem.candidate_id == reviewable_candidate.id)) is None:
            db.add(ComparisonItem(comparison_id=comparison.id, change_type="changed",
                prior_obligation_revision_id=base_obligation.current_revision_id, candidate_id=reviewable_candidate.id,
                proposed_changes={"threshold_value": {"previous": "3.50", "proposed": "4.00"}},
                rationale="Synthetic demo amendment changes the leverage threshold; reviewer decision required.", similarity=1.0))
        if db.scalar(select(AuditEvent.id).where(AuditEvent.entity_id == comparison.id,
                AuditEvent.action == "demo_amendment_comparison_created")) is None:
            db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                action="demo_amendment_comparison_created", entity_type="amendment_comparison", entity_id=comparison.id,
                summary={"status": "synthetic_demo"}))
        db.flush()

        # Monitoring records are keyed to approved obligation and revision; statuses remain illustrative.
        all_approved = list(db.scalars(select(Obligation).join(Agreement).where(
            Agreement.workspace_id == DEV_WORKSPACE_ID, Agreement.name.like(f"{DEMO_PREFIX}%"),
            Obligation.current_revision_id.is_not(None))))
        today = date.today()
        monitor_statuses = ["upcoming", "due", "awaiting_evidence", "submitted", "reviewed", "not_assessed", "awaiting_setup"]
        for index, obligation in enumerate(all_approved[:7]):
            revision = db.get(ObligationRevision, obligation.current_revision_id)
            label = f"DEMO FY2026 Q{index % 4 + 1} — {obligation.id[:8]}"
            period = db.scalar(select(MonitoringPeriod).where(MonitoringPeriod.obligation_id == obligation.id,
                MonitoringPeriod.obligation_revision_id == revision.id, MonitoringPeriod.period_label == label))
            if period is not None:
                continue
            start = date(2026, ((index % 4) * 3) + 1, 1)
            end_month = start.month + 2
            end = date(2026, end_month, 28 if end_month == 2 else 30 if end_month in (4, 6, 9, 11) else 31)
            status = monitor_statuses[index]
            due = today + timedelta(days=(index - 2) * 10) if status != "awaiting_setup" else None
            period = MonitoringPeriod(obligation_id=obligation.id, obligation_revision_id=revision.id,
                period_label=label, period_start=start, period_end=end, due_date=due,
                deadline_rule=revision.canonical_payload.get("deadline_calculation_rule"), status=status,
                created_by=user_ids["contributor"])
            db.add(period); db.flush()
            if status in {"submitted", "reviewed"}:
                db.add(MonitoringUpdate(monitoring_period_id=period.id, status=status,
                    note=f"{DEMO_PREFIX} illustrative tracker event.", supporting_reference="Synthetic demo evidence reference",
                    evidence_received_at=today, recorded_by=user_ids["reviewer"] if status == "reviewed" else user_ids["contributor"]))
            db.add(AuditEvent(workspace_id=DEV_WORKSPACE_ID, actor_user_id=user_ids["contributor"],
                action="demo_monitoring_period_created", entity_type="monitoring_period", entity_id=period.id,
                summary={"period_label": label, "status": "synthetic_demo"}))

        db.flush()
        counts = {
            "agreements": db.query(Agreement).filter(Agreement.workspace_id == DEV_WORKSPACE_ID, Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "versions": db.query(AgreementVersion).join(Agreement).filter(Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "obligations": db.query(Obligation).join(Agreement).filter(Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "candidates": db.query(ExtractionCandidate).join(ExtractionRun).join(AgreementVersion).join(Agreement).filter(Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "monitoring_periods": db.query(MonitoringPeriod).join(Obligation).join(Agreement).filter(Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "amendment_proposals": db.query(ComparisonItem).join(AmendmentComparison).join(Agreement).filter(Agreement.name.like(f"{DEMO_PREFIX}%")).count(),
            "audit_events": db.query(AuditEvent).filter(AuditEvent.workspace_id == DEV_WORKSPACE_ID,
                AuditEvent.action.like("demo_%")).count(),
        }
    return counts


def main() -> None:
    engine, session_factory = build_session_factory(DATABASE_URL)
    try:
        with engine.connect() as connection:
            # Refuse to create a schema implicitly; the documented Alembic migration step is required.
            from sqlalchemy import inspect
            tables = set(inspect(connection).get_table_names())
            if "alembic_version" not in tables:
                raise SystemExit("Database has no Alembic migration state. Run `alembic upgrade head` first.")
        result = seed_demo_data(session_factory, STORAGE_DIR)
        print("Synthetic demo seed complete (no LLM calls).")
        for key, value in result.items():
            print(f"{key}: {value}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
