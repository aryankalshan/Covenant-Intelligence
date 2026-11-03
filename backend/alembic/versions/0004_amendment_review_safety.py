"""Add extraction coverage and full-document removal attestations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_amendment_review_safety"
down_revision = "0003_review_monitoring_audit"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    with op.batch_alter_table("amendment_comparisons") as batch:
        batch.add_column(sa.Column("extraction_coverage_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("coverage_details", json_type(), nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table("comparison_decisions") as batch:
        batch.add_column(sa.Column("full_document_review_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("comparison_decisions") as batch:
        batch.drop_column("full_document_review_confirmed")
    with op.batch_alter_table("amendment_comparisons") as batch:
        batch.drop_column("coverage_details")
        batch.drop_column("extraction_coverage_complete")
