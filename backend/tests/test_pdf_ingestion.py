import hashlib
import base64
import pytest
from sqlalchemy import select, func

import pymupdf as fitz
from app.modules.agreements.models import Agreement, AgreementVersion, DocumentPage, User, UserMembership, Workspace
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.persistence import save_candidate_with_evidence, save_approved_revision_with_evidence
from app.modules.obligations.models import Evidence, Obligation, ObligationRevision


def pdf_bytes(*pages: str) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def create_agreement(client, headers):
    response = client.post("/api/v1/agreements", headers=headers, json={"name": "Synthetic Revolver", "counterparty": "Example Co"})
    assert response.status_code == 201
    return response.json()


def test_create_upload_process_and_read_page_text(client, dev_headers):
    agreement = create_agreement(client, dev_headers)
    original = pdf_bytes("Synthetic page one", "Synthetic page two")

    uploaded = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Synthetic Draft v1", "source_kind": "synthetic"},
        files={"file": ("synthetic.pdf", original, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    version = uploaded.json()
    assert version["status"] == "uploaded"
    assert version["version_label"] == "Synthetic Draft v1"
    assert version["source_kind"] == "synthetic"
    assert version["sha256"] == hashlib.sha256(original).hexdigest()

    processed = client.post(f"/api/v1/versions/{version['id']}/process", headers=dev_headers)
    assert processed.status_code == 200, processed.text
    assert processed.json()["page_count"] == 2
    assert processed.json()["status"] == "processed"

    summary = client.get(f"/api/v1/versions/{version['id']}/pages", headers=dev_headers)
    assert summary.status_code == 200
    assert [item["page_number"] for item in summary.json()] == [1, 2]
    assert all(len(item["text_sha256"]) == 64 for item in summary.json())

    page = client.get(f"/api/v1/versions/{version['id']}/pages/2", headers=dev_headers)
    assert page.status_code == 200
    assert "Synthetic page two" in page.json()["text"]
    assert page.json()["text_sha256"] == hashlib.sha256(page.json()["text"].encode()).hexdigest()

    original_response = client.get(f"/api/v1/versions/{version['id']}/pdf", headers=dev_headers)
    assert original_response.status_code == 200
    assert original_response.headers["content-type"].startswith("application/pdf")
    assert original_response.content == original


def test_upload_rejects_non_pdf(client, dev_headers):
    agreement = create_agreement(client, dev_headers)
    response = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Bad", "source_kind": "synthetic"},
        files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
    )
    assert response.status_code == 422


def test_upload_size_limit_returns_413(client, dev_headers):
    client.app.state.max_upload_bytes = 100
    agreement = create_agreement(client, dev_headers)
    response = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Too Large", "source_kind": "synthetic"},
        files={"file": ("large.pdf", b"%PDF-" + b"x" * 200, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_rejects_excessive_page_count(client, dev_headers):
    client.app.state.max_pdf_pages = 1
    agreement = create_agreement(client, dev_headers)
    response = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Too Many Pages", "source_kind": "synthetic"},
        files={"file": ("two-pages.pdf", pdf_bytes("First", "Second"), "application/pdf")},
    )
    assert response.status_code == 422


def test_empty_pdf_is_rejected(client, dev_headers):
    data = b"%PDF-1.7\n%%EOF"
    agreement = create_agreement(client, dev_headers)
    response = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Empty", "source_kind": "synthetic"},
        files={"file": ("empty.pdf", data, "application/pdf")},
    )
    assert response.status_code == 422


def test_scanned_page_has_ocr_unavailable_warning(client, dev_headers):
    document = fitz.open()
    page = document.new_page()
    # A tiny embedded image simulates an image-only scanned page; no OCR text is present.
    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/nXcAAAAASUVORK5CYII=")
    page.insert_image(page.rect, stream=image)
    data = document.tobytes()
    document.close()
    agreement = create_agreement(client, dev_headers)
    upload = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Image Only", "source_kind": "synthetic"},
        files={"file": ("scan.pdf", data, "application/pdf")},
    )
    version_id = upload.json()["id"]
    processed = client.post(f"/api/v1/versions/{version_id}/process", headers=dev_headers)
    assert processed.status_code == 200
    page_response = client.get(f"/api/v1/versions/{version_id}/pages/1", headers=dev_headers)
    assert page_response.status_code == 200
    assert page_response.json()["has_text"] is False
    assert "OCR is not enabled" in page_response.json()["warnings"][0]


def test_reprocessing_replaces_page_rows_without_duplicates(client, dev_headers):
    agreement = create_agreement(client, dev_headers)
    upload = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Original", "source_kind": "synthetic"},
        files={"file": ("repeat.pdf", pdf_bytes("First", "Second"), "application/pdf")},
    )
    version_id = upload.json()["id"]
    for _ in range(2):
        response = client.post(f"/api/v1/versions/{version_id}/process", headers=dev_headers)
        assert response.status_code == 200
    session = client.app.state.session_factory()
    try:
        count = session.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.agreement_version_id == version_id))
        assert count == 2
    finally:
        session.close()


def test_upload_requires_seeded_development_identity(client):
    response = client.post("/api/v1/agreements", json={"name": "Private"})
    assert response.status_code == 401


def test_document_pages_are_workspace_scoped_and_page_missing_is_404(client, dev_headers):
    agreement = create_agreement(client, dev_headers)
    upload = client.post(
        f"/api/v1/agreements/{agreement['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Original", "source_kind": "synthetic"},
        files={"file": ("synthetic.pdf", pdf_bytes("Hello"), "application/pdf")},
    )
    version_id = upload.json()["id"]
    client.post(f"/api/v1/versions/{version_id}/process", headers=dev_headers)
    response = client.get(f"/api/v1/versions/{version_id}/pages/2", headers=dev_headers)
    assert response.status_code == 404

    secondary_user_id = "00000000-0000-4000-8000-000000000099"
    secondary_workspace_id = "00000000-0000-4000-8000-000000000098"
    session = client.app.state.session_factory()
    try:
        session.add(Workspace(id=secondary_workspace_id, name="Secondary test workspace"))
        session.add(User(id=secondary_user_id, display_name="Secondary test contributor"))
        session.add(UserMembership(workspace_id=secondary_workspace_id, user_id=secondary_user_id, role="contributor"))
        session.commit()
    finally:
        session.close()
    client.app.state.dev_identity_ids["secondary_workspace_user"] = secondary_user_id
    secondary_agreement = client.post("/api/v1/agreements", headers={"X-Dev-User": "secondary_workspace_user"}, json={"name": "Secondary agreement"})
    assert secondary_agreement.status_code == 201
    denied = client.get(f"/api/v1/agreements/{secondary_agreement.json()['id']}", headers=dev_headers)
    assert denied.status_code == 404
    primary_list = client.get("/api/v1/agreements", headers=dev_headers)
    assert all(item["id"] != secondary_agreement.json()["id"] for item in primary_list.json())


def test_seeded_roles_are_enforced_at_api_boundary(client, dev_headers):
    reviewer_attempt = client.post("/api/v1/agreements", headers={"X-Dev-User":"reviewer"}, json={"name": "Reviewer cannot create"})
    assert reviewer_attempt.status_code == 403
    read_only = client.get("/api/v1/agreements", headers={"X-Dev-User": "read_only"})
    assert read_only.status_code == 200


def test_canonical_candidate_and_approved_payloads_store_evidence_relationally(client, dev_headers):
    agreement_out = create_agreement(client, dev_headers)
    upload = client.post(
        f"/api/v1/agreements/{agreement_out['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Original", "source_kind": "synthetic"},
        files={"file": ("synthetic.pdf", pdf_bytes("Synthetic reporting clause."), "application/pdf")},
    )
    version_id = upload.json()["id"]
    client.post(f"/api/v1/versions/{version_id}/process", headers=dev_headers)

    payload = {
        "obligation_category": "reporting_obligation",
        "obligation_description": "Deliver quarterly compliance certificate",
        "source_wording": "Synthetic reporting clause.",
        "threshold_value": None,
        "comparison_operator": None,
        "threshold_unit": None,
        "measurement_basis": None,
        "testing_frequency": "quarterly",
        "testing_period": None,
        "reporting_deadline": None,
        "deadline_calculation_rule": None,
        "conditions": None,
        "exceptions": None,
        "referenced_definitions": None,
        "cross_references": None,
        "supporting_evidence": [{"quote": "Synthetic reporting clause.", "source_page": 1, "source_section": "Section 6.2"}],
        "uncertainty_reasons": [],
    }
    db = client.app.state.session_factory()
    try:
        version = db.get(AgreementVersion, version_id)
        run = ExtractionRun(agreement_version_id=version_id, status="succeeded", schema_version="1.0.0")
        db.add(run)
        db.flush()
        candidate = save_candidate_with_evidence(db, run.id, version, payload)
        assert candidate.canonical_payload == payload
        candidate_evidence = list(db.scalars(select(Evidence).where(Evidence.candidate_id == candidate.id)))
        assert len(candidate_evidence) == 1
        assert candidate_evidence[0].quote == payload["supporting_evidence"][0]["quote"]
        assert candidate_evidence[0].page_number == 1

        agreement = db.get(Agreement, agreement_out["id"])
        obligation = Obligation(agreement_id=agreement.id)
        db.add(obligation)
        db.flush()
        reviewer = db.get(User, client.app.state.dev_identity_ids["reviewer"])
        revision = save_approved_revision_with_evidence(db, obligation, version, payload, approved_by=reviewer.id, origin_candidate_id=candidate.id)
        assert revision.canonical_payload == payload
        approved_evidence = list(db.scalars(select(Evidence).where(Evidence.obligation_revision_id == revision.id)))
        assert len(approved_evidence) == 1
        assert approved_evidence[0].quote == payload["supporting_evidence"][0]["quote"]
        db.commit()

        candidate.canonical_payload = {**payload, "obligation_description": "Changed after creation"}
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()
        revision = db.scalar(select(ObligationRevision))
        revision.canonical_payload = {**payload, "obligation_description": "Changed after approval"}
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_evidence_quote_must_match_extracted_page_before_candidate_is_saved(client, dev_headers):
    agreement_out = create_agreement(client, dev_headers)
    upload = client.post(
        f"/api/v1/agreements/{agreement_out['id']}/versions",
        headers=dev_headers,
        data={"version_label": "Original", "source_kind": "synthetic"},
        files={"file": ("synthetic.pdf", pdf_bytes("Only this text exists."), "application/pdf")},
    )
    version_id = upload.json()["id"]
    client.post(f"/api/v1/versions/{version_id}/process", headers=dev_headers)
    payload = {
        "obligation_category": "negative_covenant", "obligation_description": "Synthetic restriction",
        "source_wording": "Invented supporting quote", "threshold_value": None, "comparison_operator": None,
        "threshold_unit": None, "measurement_basis": None, "testing_frequency": None, "testing_period": None,
        "reporting_deadline": None, "deadline_calculation_rule": None, "conditions": None, "exceptions": None,
        "referenced_definitions": None, "cross_references": None,
        "supporting_evidence": [{"quote": "Invented supporting quote", "source_page": 1, "source_section": None}],
        "uncertainty_reasons": [],
    }
    db = client.app.state.session_factory()
    try:
        version = db.get(AgreementVersion, version_id)
        run = ExtractionRun(agreement_version_id=version_id, status="succeeded", schema_version="1.0.0")
        db.add(run); db.flush()
        with pytest.raises(ValueError, match="does not match"):
            save_candidate_with_evidence(db, run.id, version, payload)
        assert db.scalar(select(func.count()).select_from(ExtractionCandidate)) == 0
        db.rollback()
    finally:
        db.close()
