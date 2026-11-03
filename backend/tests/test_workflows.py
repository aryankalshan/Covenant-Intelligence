import json
from datetime import date

import pymupdf as fitz
import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.providers import MockLLMProvider
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision
from app.modules.review.models import ReviewDecision


CLAUSE = "Within 30 days after each fiscal quarter end, the Borrower shall deliver quarterly compliance certificate."


def make_pdf(text: str) -> bytes:
    if "Debt-to-EBITDA" in text and "means" not in text:
        text += "\nDebt-to-EBITDA means the ratio of Consolidated Total Debt to Consolidated EBITDA."
    doc = fitz.open(); doc.new_page().insert_text((50, 60), text, fontsize=9)
    result = doc.tobytes(); doc.close(); return result


def payload(text: str = CLAUSE, *, category="reporting_obligation", description="Quarterly compliance certificate", threshold=None, uncertainty=None):
    return {
        "obligation_category": category, "obligation_description": description, "source_wording": text,
        "threshold_value": threshold, "comparison_operator": "<=" if threshold else None,
        "threshold_unit": "x" if threshold else None, "measurement_basis": "Debt-to-EBITDA" if threshold else None,
        "testing_frequency": "quarterly", "testing_period": "Each fiscal quarter", "reporting_deadline": "Within 30 days" if not threshold else None,
        "deadline_calculation_rule": "Within 30 days after each fiscal quarter end" if not threshold else None,
        "conditions": None, "exceptions": None, "referenced_definitions": None, "cross_references": None,
        "supporting_evidence": [{"quote": text, "source_page": 1, "source_section": "Section 5.1"}], "uncertainty_reasons": uncertainty or [],
    }


def create_agreement(client, name="Workflow Synthetic Facility"):
    response = client.post("/api/v1/agreements", headers={"X-Dev-User":"contributor"}, json={"name":name,"counterparty":"Fictional Company"})
    assert response.status_code == 201, response.text
    return response.json()


def create_version(client, agreement_id: str, text: str, label: str):
    response = client.post(f"/api/v1/agreements/{agreement_id}/versions", headers={"X-Dev-User":"contributor"},
        data={"version_label":label,"source_kind":"synthetic"}, files={"file":(f"{label}.pdf",make_pdf(text),"application/pdf")})
    assert response.status_code == 201, response.text
    version_id = response.json()["id"]
    processed = client.post(f"/api/v1/versions/{version_id}/process", headers={"X-Dev-User":"contributor"})
    assert processed.status_code == 200, processed.text
    return response.json()


def create_candidate(client, agreement_id: str, text: str = CLAUSE, *, label="Original", obligation_payload=None):
    version = create_version(client, agreement_id, text, label)
    provider_payload = obligation_payload or payload(text)
    client.app.state.provider_factory = lambda: MockLLMProvider([json.dumps({"schema_version":"1.1.0","obligations":[provider_payload]})])
    run_response = client.post(f"/api/v1/versions/{version['id']}/extraction-runs", headers={"X-Dev-User":"contributor"}, json={})
    assert run_response.status_code == 202, run_response.text
    run = client.get(f"/api/v1/extraction-runs/{run_response.json()['id']}", headers={"X-Dev-User":"contributor"}).json()
    assert run["status"] == "succeeded", json.dumps(run, indent=2)
    candidates = client.get(f"/api/v1/extraction-runs/{run['id']}/candidates", headers={"X-Dev-User":"contributor"}).json()
    assert len(candidates) == 1
    return version, run, candidates[0]


def approve_candidate(client, candidate_id: str):
    response = client.post(f"/api/v1/candidates/{candidate_id}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"approved"})
    assert response.status_code == 201, response.text
    return response.json()


def test_reviewer_approval_creates_immutable_revision_evidence_and_audit(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    approved = approve_candidate(client, candidate["id"])
    assert approved["revision_id"]
    assert client.get("/api/v1/obligations", headers={"X-Dev-User":"read_only"}).json()[0]["id"] == approved["obligation_id"]
    detail = client.get(f"/api/v1/obligations/{approved['obligation_id']}", headers={"X-Dev-User":"reviewer"}).json()
    assert detail["current"]["canonical_payload"] == candidate["canonical_payload"]
    assert detail["current"]["evidence"][0]["quote"] == CLAUSE
    db = client.app.state.session_factory()
    try:
        original = db.get(ExtractionCandidate, candidate["id"])
        assert original.canonical_payload == candidate["canonical_payload"]
        assert db.scalar(select(ReviewDecision).where(ReviewDecision.candidate_id == candidate["id"])).decision == "approved"
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "candidate_approved"))
        revision = db.get(ObligationRevision, approved["revision_id"])
        revision.canonical_payload = {**revision.canonical_payload, "obligation_description":"mutated"}
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_contributor_and_read_only_cannot_review_or_mutate(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    for identity in ("contributor", "read_only"):
        response = client.post(f"/api/v1/candidates/{candidate['id']}/review-decisions", headers={"X-Dev-User":identity}, json={"action":"rejected"})
        assert response.status_code == 403
    assert client.get("/api/v1/review/candidates", headers={"X-Dev-User":"reviewer"}).status_code == 200


def test_corrected_candidate_is_complete_and_original_extraction_is_unchanged(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    replacement = {**candidate["canonical_payload"], "obligation_description":"Quarterly certificate delivery"}
    response = client.post(f"/api/v1/candidates/{candidate['id']}/review-decisions", headers={"X-Dev-User":"reviewer"},
        json={"action":"corrected","corrected_obligation":replacement,"comment":"Description checked against cited clause."})
    assert response.status_code == 201, response.text
    assert client.get(f"/api/v1/candidates/{candidate['id']}", headers={"X-Dev-User":"reviewer"}).json()["canonical_payload"] == candidate["canonical_payload"]
    current = client.get(f"/api/v1/obligations/{response.json()['obligation_id']}", headers={"X-Dev-User":"reviewer"}).json()["current"]
    assert current["canonical_payload"]["obligation_description"] == "Quarterly certificate delivery"


def test_invalid_corrected_evidence_prevents_approval_and_uncertainty_needs_comment(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    invalid = {**candidate["canonical_payload"], "supporting_evidence":[{"quote":"not in the source", "source_page":1,"source_section":None}]}
    blocked = client.post(f"/api/v1/candidates/{candidate['id']}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"corrected","corrected_obligation":invalid,"comment":"Correction"})
    assert blocked.status_code == 422
    uncertain_payload = payload(CLAUSE, description="Potential covenant", uncertainty=["Needs source check."])
    _, _, uncertain = create_candidate(client, agreement["id"], label="Uncertain", obligation_payload=uncertain_payload)
    cleaned = {**uncertain["canonical_payload"], "uncertainty_reasons":[]}
    no_comment = client.post(f"/api/v1/candidates/{uncertain['id']}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"corrected","corrected_obligation":cleaned})
    assert no_comment.status_code == 422
    reviewed = client.post(f"/api/v1/candidates/{uncertain['id']}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"corrected","corrected_obligation":cleaned,"comment":"Reviewed the cited page and resolved the uncertainty."})
    assert reviewed.status_code == 201


def test_reject_and_needs_information_are_audited_without_approval(client):
    agreement = create_agreement(client)
    _, _, pending = create_candidate(client, agreement["id"], label="Pending")
    response = client.post(f"/api/v1/candidates/{pending['id']}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"needs_information","comment":"Request source exhibit."})
    assert response.status_code == 201
    queue = client.get("/api/v1/review/candidates", headers={"X-Dev-User":"reviewer"}).json()
    assert pending["id"] in {row["id"] for row in queue}
    _, _, rejected = create_candidate(client, agreement["id"], label="Reject")
    response = client.post(f"/api/v1/candidates/{rejected['id']}/review-decisions", headers={"X-Dev-User":"reviewer"}, json={"action":"rejected","comment":"Not an operative clause."})
    assert response.status_code == 201
    assert rejected["id"] not in {row["id"] for row in client.get("/api/v1/review/candidates", headers={"X-Dev-User":"reviewer"}).json()}
    actions = {row["action"] for row in client.get("/api/v1/audit-events", headers={"X-Dev-User":"read_only"}).json()}
    assert {"candidate_needs_information", "candidate_rejected"} <= actions


def test_monitoring_deadline_calculation_overdue_derivation_and_submitted_exclusion(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    approved = approve_candidate(client, candidate["id"])
    body = {"period_label":"FY2026 Q1","period_start":"2026-01-01","period_end":"2026-03-31"}
    created = client.post(f"/api/v1/obligations/{approved['obligation_id']}/monitoring-periods", headers={"X-Dev-User":"reviewer"}, json=body)
    assert created.status_code == 201, created.text
    period = created.json()
    assert period["due_date"] == "2026-04-30"
    assert period["deadline_resolution"] == "calculated"
    assert period["is_overdue"] is True
    submitted = client.post(f"/api/v1/monitoring-periods/{period['id']}/updates", headers={"X-Dev-User":"reviewer"}, json={"status":"submitted","supporting_reference":"synthetic://certificate","evidence_received_at":"2026-04-20"})
    assert submitted.status_code == 201
    assert submitted.json()["is_overdue"] is False
    invalid = client.post(f"/api/v1/monitoring-periods/{period['id']}/updates", headers={"X-Dev-User":"reviewer"}, json={"status":"overdue"})
    assert invalid.status_code == 422
    duplicate = client.post(f"/api/v1/obligations/{approved['obligation_id']}/monitoring-periods", headers={"X-Dev-User":"reviewer"}, json=body)
    assert duplicate.status_code == 409


def test_monitoring_updates_are_role_scoped(client):
    agreement = create_agreement(client)
    _, _, candidate = create_candidate(client, agreement["id"])
    approved = approve_candidate(client, candidate["id"])
    created = client.post(
        f"/api/v1/obligations/{approved['obligation_id']}/monitoring-periods",
        headers={"X-Dev-User": "contributor"},
        json={"period_label": "FY2026 Q2", "period_start": "2026-04-01", "period_end": "2026-06-30", "due_date": "2026-07-30"},
    )
    assert created.status_code == 201, created.text
    period_id = created.json()["id"]

    progress = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "contributor"}, json={"status": "awaiting_evidence"})
    assert progress.status_code == 201, progress.text
    submission = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "contributor"}, json={"status": "submitted", "supporting_reference": "synthetic://quarterly-certificate"})
    assert submission.status_code == 201, submission.text

    for status in ("reviewed", "not_applicable", "not_assessed"):
        denied = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "contributor"}, json={"status": status})
        assert denied.status_code == 403, (status, denied.text)
    read_only_denied = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "read_only"}, json={"status": "submitted"})
    assert read_only_denied.status_code == 403

    reviewed = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "reviewer"}, json={"status": "reviewed", "note": "Evidence checked."})
    assert reviewed.status_code == 201, reviewed.text
    not_applicable = client.post(f"/api/v1/monitoring-periods/{period_id}/updates", headers={"X-Dev-User": "admin"}, json={"status": "not_applicable", "note": "Reviewer confirmed the exception."})
    assert not_applicable.status_code == 201, not_applicable.text


def test_ambiguous_deadline_remains_awaiting_setup(client):
    agreement = create_agreement(client)
    text = "Within 30 business days after fiscal year end, the Borrower shall deliver annual audited financial statements."
    rule_payload = payload(text, description="Annual audit", category="reporting_obligation")
    rule_payload["reporting_deadline"] = "Within 30 business days"
    rule_payload["deadline_calculation_rule"] = "Within 30 business days after fiscal year end"
    _, _, candidate = create_candidate(client, agreement["id"], text, obligation_payload=rule_payload)
    approved = approve_candidate(client, candidate["id"])
    response = client.post(f"/api/v1/obligations/{approved['obligation_id']}/monitoring-periods", headers={"X-Dev-User":"reviewer"}, json={"period_label":"FY2026","period_start":"2026-01-01","period_end":"2026-12-31","fiscal_year_end":"2026-12-31"})
    assert response.status_code == 201, response.text
    assert response.json()["due_date"] is None
    assert response.json()["status"] == "awaiting_setup"
    assert response.json()["deadline_resolution"] == "needs_configuration"


def debt_payload(text: str, threshold: str):
    result = payload(text, category="financial_covenant", description="Maximum Debt-to-EBITDA", threshold=threshold)
    result.update({"reporting_deadline":None,"deadline_calculation_rule":None,"testing_frequency":"quarterly","testing_period":"Quarter end"})
    return result


def test_amendment_threshold_change_requires_review_and_creates_new_revision(client):
    agreement = create_agreement(client)
    old_text = "The Borrower shall not permit Debt-to-EBITDA to exceed 3.50x at each quarter end."
    base_version, _, old_candidate = create_candidate(client, agreement["id"], old_text, label="Original", obligation_payload=debt_payload(old_text,"3.50"))
    approved = approve_candidate(client, old_candidate["id"])
    new_text = "The Borrower shall not permit Debt-to-EBITDA to exceed 4.00x at each quarter end."
    new_version, run, new_candidate = create_candidate(client, agreement["id"], new_text, label="Amendment 1", obligation_payload=debt_payload(new_text,"4.00"))
    comparison = client.post(f"/api/v1/agreements/{agreement['id']}/amendment-comparisons", headers={"X-Dev-User":"contributor"}, json={"base_version_id":base_version["id"],"amendment_version_id":new_version["id"],"extraction_run_id":run["id"]})
    assert comparison.status_code == 201, comparison.text
    item = comparison.json()["items"][0]
    assert item["change_type"] == "changed"
    assert item["proposed_changes"]["threshold_value"] == {"previous":"3.50","proposed":"4.00"}
    accepted = client.post(f"/api/v1/comparison-items/{item['id']}/decisions", headers={"X-Dev-User":"reviewer"}, json={"decision":"accepted"})
    assert accepted.status_code == 201, accepted.text
    history = client.get(f"/api/v1/obligations/{approved['obligation_id']}/revisions", headers={"X-Dev-User":"reviewer"}).json()
    assert len(history) == 2
    assert history[0]["canonical_payload"]["threshold_value"] == "4.00"
    assert history[1]["status"] == "superseded"
    assert client.get(f"/api/v1/candidates/{new_candidate['id']}", headers={"X-Dev-User":"reviewer"}).json()["canonical_payload"]["threshold_value"] == "4.00"


def test_rejected_amendment_proposal_does_not_change_register_and_cross_agreement_is_blocked(client):
    agreement = create_agreement(client)
    old_text = "The Borrower shall not permit Debt-to-EBITDA to exceed 3.50x at each quarter end."
    base_version, _, candidate = create_candidate(client, agreement["id"], old_text, obligation_payload=debt_payload(old_text,"3.50"))
    approved = approve_candidate(client, candidate["id"])
    new_text = "The Borrower shall not permit Debt-to-EBITDA to exceed 4.25x at each quarter end."
    amendment, run, _ = create_candidate(client, agreement["id"], new_text, label="Amendment", obligation_payload=debt_payload(new_text,"4.25"))
    other = create_agreement(client, "Other Synthetic Facility")
    other_version, _, _ = create_candidate(client, other["id"], new_text)
    invalid = client.post(f"/api/v1/agreements/{agreement['id']}/amendment-comparisons", headers={"X-Dev-User":"contributor"}, json={"base_version_id":other_version["id"],"amendment_version_id":amendment["id"],"extraction_run_id":run["id"]})
    assert invalid.status_code == 422
    comparison = client.post(f"/api/v1/agreements/{agreement['id']}/amendment-comparisons", headers={"X-Dev-User":"contributor"}, json={"base_version_id":base_version["id"],"amendment_version_id":amendment["id"],"extraction_run_id":run["id"]}).json()
    item = comparison["items"][0]
    rejected = client.post(f"/api/v1/comparison-items/{item['id']}/decisions", headers={"X-Dev-User":"reviewer"}, json={"decision":"rejected"})
    assert rejected.status_code == 201
    current = client.get(f"/api/v1/obligations/{approved['obligation_id']}", headers={"X-Dev-User":"reviewer"}).json()["current"]
    assert current["canonical_payload"]["threshold_value"] == "3.50"


def test_partial_amendment_extraction_cannot_claim_removal_without_full_document_attestation(client):
    agreement = create_agreement(client)
    old_text = "The Borrower shall not permit Debt-to-EBITDA to exceed 3.50x at each quarter end."
    base_version, _, old_candidate = create_candidate(client, agreement["id"], old_text, label="Original", obligation_payload=debt_payload(old_text, "3.50"))
    approved = approve_candidate(client, old_candidate["id"])

    omitted_clause = "The Borrower shall not permit Debt-to-EBITDA to exceed 3.50x at each quarter end."
    reported_clause = "Within 30 days after each fiscal quarter end, the Borrower shall deliver quarterly compliance certificate."
    amendment_text = omitted_clause + "\n" + reported_clause
    amended_version, run, _ = create_candidate(client, agreement["id"], amendment_text, label="Partial Amendment", obligation_payload=payload(reported_clause, description="Quarterly compliance certificate"))
    db = client.app.state.session_factory()
    try:
        stored_run = db.get(ExtractionRun, run["id"])
        stored_run.status = "partial"
        stored_run.chunk_count = 2
        stored_run.processed_chunk_count = 1
        stored_run.unprocessed_chunk_count = 1
        stored_run.screened_out_chunk_count = 1
        db.commit()
    finally:
        db.close()

    comparison = client.post(f"/api/v1/agreements/{agreement['id']}/amendment-comparisons", headers={"X-Dev-User": "contributor"}, json={
        "base_version_id": base_version["id"], "amendment_version_id": amended_version["id"], "extraction_run_id": run["id"],
    })
    assert comparison.status_code == 201, comparison.text
    removal = next(item for item in comparison.json()["items"] if item["prior_obligation_revision_id"])
    assert removal["change_type"] == "unresolved"
    assert removal["extraction_coverage"]["complete"] is False
    assert removal["extraction_coverage"]["unprocessed_chunk_count"] == 1
    assert removal["extraction_coverage"]["screened_out_chunk_count"] == 1
    assert removal["prior_obligation"]["canonical_payload"]["threshold_value"] == "3.50"
    assert removal["prior_obligation"]["evidence"][0]["quote"] == old_text
    assert removal["amendment_version"]["id"] == amended_version["id"]

    review_material = client.get(f"/api/v1/comparison-items/{removal['id']}/removal-review", headers={"X-Dev-User": "reviewer"})
    assert review_material.status_code == 200
    assert any(omitted_clause in page["text"] for page in review_material.json()["pages"])
    current = client.get(f"/api/v1/obligations/{approved['obligation_id']}", headers={"X-Dev-User": "reviewer"}).json()
    assert current["lifecycle_status"] == "active"

    no_attestation = client.post(f"/api/v1/comparison-items/{removal['id']}/decisions", headers={"X-Dev-User": "reviewer"}, json={"decision": "accepted", "comment": "Reviewed the wording."})
    assert no_attestation.status_code == 422
    still_active = client.get(f"/api/v1/obligations/{approved['obligation_id']}", headers={"X-Dev-User": "reviewer"}).json()
    assert still_active["lifecycle_status"] == "active"

    confirmed = client.post(f"/api/v1/comparison-items/{removal['id']}/decisions", headers={"X-Dev-User": "reviewer"}, json={
        "decision": "accepted", "comment": "I reviewed every page of the complete amendment; the original debt covenant is absent.", "full_document_review_confirmed": True,
    })
    assert confirmed.status_code == 201, confirmed.text
    db = client.app.state.session_factory()
    try:
        decision = db.scalar(select(ReviewDecision).where(ReviewDecision.candidate_id == old_candidate["id"]))
        from app.modules.amendments.models import ComparisonDecision
        accepted_decision = db.scalar(select(ComparisonDecision).where(ComparisonDecision.comparison_item_id == removal["id"]).order_by(ComparisonDecision.created_at.desc()))
        assert accepted_decision.full_document_review_confirmed is True
        assert accepted_decision.comment.startswith("I reviewed every page")
    finally:
        db.close()
    final = client.get(f"/api/v1/obligations/{approved['obligation_id']}", headers={"X-Dev-User": "reviewer"}).json()
    assert final["lifecycle_status"] == "superseded"
