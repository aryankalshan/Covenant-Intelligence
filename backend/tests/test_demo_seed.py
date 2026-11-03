from sqlalchemy import func, select

from app.modules.agreements.models import Agreement, AgreementVersion, DocumentPage
from app.modules.amendments.models import ComparisonItem
from app.modules.audit.models import AuditEvent
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.monitoring.models import MonitoringPeriod
from app.modules.obligations.models import Evidence, Obligation
from app.scripts.seed_demo import DEMO_PREFIX, seed_demo_data


def test_demo_seed_is_repeatable_and_all_evidence_matches_synthetic_pages(client, tmp_path):
    counts_first = seed_demo_data(client.app.state.session_factory, tmp_path / "demo-storage")
    counts_second = seed_demo_data(client.app.state.session_factory, tmp_path / "demo-storage")

    assert counts_first == counts_second
    assert counts_first["agreements"] == 3
    assert counts_first["versions"] == 4
    assert counts_first["obligations"] >= 10
    assert counts_first["candidates"] >= 5
    assert counts_first["monitoring_periods"] >= 6
    assert counts_first["amendment_proposals"] >= 1
    assert counts_first["audit_events"] > 0

    db = client.app.state.session_factory()
    try:
        agreements = list(db.scalars(select(Agreement).where(Agreement.name.like(f"{DEMO_PREFIX}%"))))
        agreement_ids = {item.id for item in agreements}
        versions = list(db.scalars(select(AgreementVersion).where(AgreementVersion.agreement_id.in_(agreement_ids))))
        version_ids = {item.id for item in versions}
        pages = {(item.agreement_version_id, item.page_number): item for item in db.scalars(
            select(DocumentPage).where(DocumentPage.agreement_version_id.in_(version_ids))
        )}

        for candidate in db.scalars(select(ExtractionCandidate).join(ExtractionRun).where(
            ExtractionRun.agreement_version_id.in_(version_ids)
        )):
            CanonicalObligation.model_validate(candidate.canonical_payload)
            assert candidate.status == "awaiting_review"
            run = db.get(ExtractionRun, candidate.extraction_run_id)
            assert run.provider == "synthetic_demo"
            assert run.provider_metadata.get("llm_called") is False

        evidence_rows = list(db.scalars(select(Evidence).where(Evidence.agreement_version_id.in_(version_ids))))
        assert evidence_rows
        for evidence in evidence_rows:
            source_page = pages[(evidence.agreement_version_id, evidence.page_number)]
            assert evidence.quote in source_page.text or " ".join(evidence.quote.split()) in " ".join(source_page.text.split())

        assert db.scalar(select(func.count()).select_from(Obligation).where(Obligation.agreement_id.in_(agreement_ids))) >= 10
        assert db.scalar(select(func.count()).select_from(ComparisonItem)) >= 1
        assert db.scalar(select(func.count()).select_from(MonitoringPeriod)) >= 6
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("demo_%"))) > 0
    finally:
        db.close()
