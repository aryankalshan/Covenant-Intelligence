"""Add extraction run tracking fields and enforce seeded role vocabulary."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_extraction_metadata"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _checks(table):
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints(table)}


def _unique_constraints(table):
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_unique_constraints(table)}


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    run_columns = _columns("extraction_runs")
    run_additions = [
        sa.Column("prompt_version", sa.String(40), nullable=False, server_default="covenant-extraction-v1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id", name="fk_extraction_runs_requested_by_users"), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_categories", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("validation_findings", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("provider_metadata", _json_type(), nullable=False, server_default=sa.text("'{}'")),
    ]
    with op.batch_alter_table("extraction_runs") as batch:
        for column in run_additions:
            if column.name not in run_columns:
                batch.add_column(column)

    candidate_columns = _columns("extraction_candidates")
    candidate_additions = [
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="awaiting_review"),
        sa.Column("validation_status", sa.String(30), nullable=False, server_default="needs_review"),
        sa.Column("validation_findings", _json_type(), nullable=False, server_default=sa.text("'[]'")),
    ]
    with op.batch_alter_table("extraction_candidates") as batch:
        for column in candidate_additions:
            if column.name not in candidate_columns:
                batch.add_column(column)

    if "ck_user_membership_role" not in _checks("user_memberships"):
        with op.batch_alter_table("user_memberships") as batch:
            batch.create_check_constraint(
                "ck_user_membership_role",
                "role IN ('admin', 'reviewer', 'contributor', 'read_only')",
            )

    if "uq_obligation_revision_number" not in _unique_constraints("obligation_revisions"):
        with op.batch_alter_table("obligation_revisions") as batch:
            batch.create_unique_constraint("uq_obligation_revision_number", ["obligation_id", "revision_number"])

    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("extraction_candidates")}
    if "ix_extraction_candidates_category_status" not in indexes:
        op.create_index("ix_extraction_candidates_category_status", "extraction_candidates", ["category", "status"])


def downgrade():
    # Preserve extracted and review data; forward-only migration is safer for this data-bearing schema.
    pass
