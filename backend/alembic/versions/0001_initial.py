"""Explicit baseline schema; safely adopts tables created by the former startup create_all."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_table_if_missing(name, *columns, **kwargs):
    if name not in _tables():
        op.create_table(name, *columns, **kwargs)


def _ensure_index(name, table, columns, unique=False):
    if table in _tables() and name not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    _create_table_if_missing(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    _create_table_if_missing(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
    )
    _create_table_if_missing(
        "user_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_user_membership_workspace_user"),
        sa.CheckConstraint("role IN ('admin', 'reviewer', 'contributor', 'read_only')", name="ck_user_membership_role"),
    )
    _create_table_if_missing(
        "agreements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("counterparty", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
    )
    _create_table_if_missing(
        "agreement_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_id", sa.String(36), sa.ForeignKey("agreements.id"), nullable=False),
        sa.Column("version_label", sa.String(200), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
    )
    _create_table_if_missing(
        "document_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_version_id", sa.String(36), sa.ForeignKey("agreement_versions.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(30), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("agreement_version_id", "page_number", name="uq_document_page_version_number"),
    )
    _create_table_if_missing(
        "extraction_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_version_id", sa.String(36), sa.ForeignKey("agreement_versions.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("model", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    _create_table_if_missing(
        "extraction_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("canonical_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_table_if_missing(
        "obligations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_id", sa.String(36), sa.ForeignKey("agreements.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_table_if_missing(
        "obligation_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("canonical_payload", json_type, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin_candidate_id", sa.String(36), sa.ForeignKey("extraction_candidates.id")),
        sa.Column("review_decision_id", sa.String(36)),
        sa.UniqueConstraint("obligation_id", "revision_number", name="uq_obligation_revision_number"),
    )
    _create_table_if_missing(
        "evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_version_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("source_section", sa.String(300)),
        sa.Column("evidence_role", sa.String(40), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("extraction_candidates.id")),
        sa.Column("obligation_revision_id", sa.String(36), sa.ForeignKey("obligation_revisions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agreement_version_id", "page_number"],
            ["document_pages.agreement_version_id", "document_pages.page_number"],
            name="fk_evidence_document_page",
        ),
        sa.CheckConstraint(
            "(candidate_id IS NOT NULL AND obligation_revision_id IS NULL) OR "
            "(candidate_id IS NULL AND obligation_revision_id IS NOT NULL)",
            name="ck_evidence_one_owner",
        ),
    )

    for name, table, columns, unique in [
        ("ix_agreements_workspace_id", "agreements", ["workspace_id"], False),
        ("ix_agreement_versions_agreement_id", "agreement_versions", ["agreement_id"], False),
        ("ix_agreement_versions_sha256", "agreement_versions", ["sha256"], False),
        ("ix_document_pages_agreement_version_id", "document_pages", ["agreement_version_id"], False),
        ("ix_extraction_runs_agreement_version_id", "extraction_runs", ["agreement_version_id"], False),
        ("ix_extraction_candidates_extraction_run_id", "extraction_candidates", ["extraction_run_id"], False),
        ("ix_obligations_agreement_id", "obligations", ["agreement_id"], False),
        ("ix_obligation_revisions_obligation_id", "obligation_revisions", ["obligation_id"], False),
        ("ix_evidence_candidate_id", "evidence", ["candidate_id"], False),
        ("ix_evidence_obligation_revision_id", "evidence", ["obligation_revision_id"], False),
    ]:
        _ensure_index(name, table, columns, unique)


def downgrade():
    # Initial migration rollback is intentionally empty to avoid destructive deletion of user data.
    pass
