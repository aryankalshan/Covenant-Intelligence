from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.modules.agreements.models import new_id, utcnow

json_type = JSON().with_variant(JSONB, "postgresql")


class AmendmentComparison(Base):
    __tablename__ = "amendment_comparisons"
    __table_args__ = (CheckConstraint("status IN ('running', 'ready_for_review', 'completed', 'failed')", name="ck_amendment_comparison_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreements.id"), nullable=False, index=True)
    base_version_id: Mapped[str] = mapped_column(ForeignKey("agreement_versions.id"), nullable=False)
    amendment_version_id: Mapped[str] = mapped_column(ForeignKey("agreement_versions.id"), nullable=False)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False, default="deterministic-v1")
    extraction_coverage_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coverage_details: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)


class ComparisonItem(Base):
    __tablename__ = "comparison_items"
    __table_args__ = (
        CheckConstraint("change_type IN ('added', 'changed', 'removed', 'possible_match', 'unresolved')", name="ck_comparison_item_change_type"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'deferred')", name="ck_comparison_item_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("amendment_comparisons.id"), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prior_obligation_revision_id: Mapped[str | None] = mapped_column(ForeignKey("obligation_revisions.id"))
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("extraction_candidates.id"))
    proposed_changes: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")


class ComparisonDecision(Base):
    __tablename__ = "comparison_decisions"
    __table_args__ = (CheckConstraint("decision IN ('accepted', 'rejected', 'deferred')", name="ck_comparison_decision_action"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    comparison_item_id: Mapped[str] = mapped_column(ForeignKey("comparison_items.id"), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    full_document_review_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
