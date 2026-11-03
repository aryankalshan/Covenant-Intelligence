from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.modules.agreements.models import new_id, utcnow
from app.modules.extraction.models import json_payload_type


class Obligation(Base):
    __tablename__ = "obligations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreements.id"), nullable=False, index=True)
    current_revision_id: Mapped[str | None] = mapped_column(ForeignKey("obligation_revisions.id", name="fk_obligation_current_revision"))
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ObligationRevision(Base):
    __tablename__ = "obligation_revisions"
    __table_args__ = (UniqueConstraint("obligation_id", "revision_number", name="uq_obligation_revision_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_payload: Mapped[dict] = mapped_column(json_payload_type, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="approved")
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    origin_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("extraction_candidates.id"))
    review_decision_id: Mapped[str | None] = mapped_column(ForeignKey("review_decisions.id"))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agreement_version_id", "page_number"],
            ["document_pages.agreement_version_id", "document_pages.page_number"],
            name="fk_evidence_document_page",
        ),
        CheckConstraint(
            "(candidate_id IS NOT NULL AND obligation_revision_id IS NULL) OR "
            "(candidate_id IS NULL AND obligation_revision_id IS NOT NULL)",
            name="ck_evidence_one_owner",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_section: Mapped[str | None] = mapped_column(String(300))
    evidence_role: Mapped[str] = mapped_column(String(40), nullable=False, default="operative_clause")
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("extraction_candidates.id"), index=True)
    obligation_revision_id: Mapped[str | None] = mapped_column(ForeignKey("obligation_revisions.id"), index=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@event.listens_for(ObligationRevision, "before_update")
def prevent_approved_payload_mutation(mapper, connection, target):
    if inspect(target).attrs.canonical_payload.history.has_changes():
        raise ValueError("Approved canonical payloads are immutable; create a new obligation revision.")
