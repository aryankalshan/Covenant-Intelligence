"""Add human review, monitoring, amendment comparison and audit records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_review_monitoring_audit"
down_revision = "0002_extraction_metadata"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    with op.batch_alter_table("extraction_runs") as batch:
        batch.add_column(sa.Column("unprocessed_chunk_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("screened_out_chunk_count", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("obligations") as batch:
        batch.add_column(sa.Column("current_revision_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lifecycle_status", sa.String(30), nullable=False, server_default="active"))
        batch.add_column(sa.Column("created_by", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_obligation_current_revision", "obligation_revisions", ["current_revision_id"], ["id"])
        batch.create_foreign_key("fk_obligations_created_by_users", "users", ["created_by"], ["id"])
        batch.create_check_constraint("ck_obligation_lifecycle_status", "lifecycle_status IN ('active', 'superseded', 'terminated', 'closed')")

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("extraction_candidates.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_decision_id", sa.String(36), sa.ForeignKey("review_decisions.id")),
        sa.CheckConstraint("decision IN ('approved', 'corrected', 'rejected', 'needs_information')", name="ck_review_decision_action"),
    )
    op.create_index("ix_review_decisions_candidate_id", "review_decisions", ["candidate_id"])
    with op.batch_alter_table("obligation_revisions") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("review_decision_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_obligation_revision_review_decision", "review_decisions", ["review_decision_id"], ["id"])

    op.create_table(
        "monitoring_periods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("obligation_revision_id", sa.String(36), sa.ForeignKey("obligation_revisions.id"), nullable=False),
        sa.Column("period_label", sa.String(100), nullable=False),
        sa.Column("fiscal_year_end", sa.Date()),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("deadline_rule", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="awaiting_setup"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("obligation_id", "obligation_revision_id", "period_label", name="uq_monitoring_period_identity"),
        sa.CheckConstraint("status IN ('awaiting_setup','upcoming','due','awaiting_evidence','submitted','reviewed','not_assessed','not_applicable')", name="ck_monitoring_period_status"),
        sa.CheckConstraint("period_end >= period_start", name="ck_monitoring_period_date_order"),
    )
    op.create_index("ix_monitoring_periods_obligation_id", "monitoring_periods", ["obligation_id"])
    op.create_index("ix_monitoring_periods_due_date", "monitoring_periods", ["due_date"])
    op.create_table(
        "monitoring_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("monitoring_period_id", sa.String(36), sa.ForeignKey("monitoring_periods.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("supporting_reference", sa.String(500)),
        sa.Column("evidence_received_at", sa.Date()),
        sa.Column("recorded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('awaiting_setup','upcoming','due','awaiting_evidence','submitted','reviewed','not_assessed','not_applicable')", name="ck_monitoring_update_status"),
    )
    op.create_index("ix_monitoring_updates_monitoring_period_id", "monitoring_updates", ["monitoring_period_id"])

    op.create_table(
        "amendment_comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agreement_id", sa.String(36), sa.ForeignKey("agreements.id"), nullable=False),
        sa.Column("base_version_id", sa.String(36), sa.ForeignKey("agreement_versions.id"), nullable=False),
        sa.Column("amendment_version_id", sa.String(36), sa.ForeignKey("agreement_versions.id"), nullable=False),
        sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("algorithm_version", sa.String(40), nullable=False, server_default="deterministic-v1"),
        sa.CheckConstraint("status IN ('running','ready_for_review','completed','failed')", name="ck_amendment_comparison_status"),
    )
    op.create_index("ix_amendment_comparisons_agreement_id", "amendment_comparisons", ["agreement_id"])
    op.create_table(
        "comparison_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("comparison_id", sa.String(36), sa.ForeignKey("amendment_comparisons.id"), nullable=False),
        sa.Column("change_type", sa.String(30), nullable=False),
        sa.Column("prior_obligation_revision_id", sa.String(36), sa.ForeignKey("obligation_revisions.id")),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("extraction_candidates.id")),
        sa.Column("proposed_changes", json_type(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("similarity", sa.Float()),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.CheckConstraint("change_type IN ('added','changed','removed','possible_match','unresolved')", name="ck_comparison_item_change_type"),
        sa.CheckConstraint("status IN ('pending','accepted','rejected','deferred')", name="ck_comparison_item_status"),
    )
    op.create_index("ix_comparison_items_comparison_id", "comparison_items", ["comparison_id"])
    op.create_table(
        "comparison_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("comparison_item_id", sa.String(36), sa.ForeignKey("comparison_items.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('accepted','rejected','deferred')", name="ck_comparison_decision_action"),
    )
    op.create_index("ix_comparison_decisions_comparison_item_id", "comparison_decisions", ["comparison_item_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("summary", json_type(), nullable=False),
        sa.CheckConstraint("length(action) > 0", name="ck_audit_action_nonempty"),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade():
    # Forward-only to protect review and audit history.
    pass
