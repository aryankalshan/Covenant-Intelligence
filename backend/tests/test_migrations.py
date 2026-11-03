from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_alembic_builds_fresh_isolated_database_without_orm_create_all(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "alembic_version" in inspector.get_table_names()
            assert {"workspaces", "agreements", "agreement_versions", "document_pages", "extraction_runs", "extraction_candidates", "obligations", "obligation_revisions", "evidence", "review_decisions", "monitoring_periods", "monitoring_updates", "amendment_comparisons", "comparison_items", "comparison_decisions", "audit_events"} <= set(inspector.get_table_names())
            assert {"prompt_version", "validation_findings", "provider_metadata", "unprocessed_chunk_count", "screened_out_chunk_count"} <= {column["name"] for column in inspector.get_columns("extraction_runs")}
            assert {"canonical_payload", "review_decision_id", "created_at"} <= {column["name"] for column in inspector.get_columns("obligation_revisions")}
            assert {"extraction_coverage_complete", "coverage_details"} <= {column["name"] for column in inspector.get_columns("amendment_comparisons")}
            assert "full_document_review_confirmed" in {column["name"] for column in inspector.get_columns("comparison_decisions")}
    finally:
        engine.dispose()
