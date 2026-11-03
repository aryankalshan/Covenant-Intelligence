from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.agreements.models import new_id, utcnow


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (CheckConstraint("decision IN ('approved', 'corrected', 'rejected', 'needs_information')", name="ck_review_decision_action"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("extraction_candidates.id"), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    supersedes_decision_id: Mapped[str | None] = mapped_column(ForeignKey("review_decisions.id"))
