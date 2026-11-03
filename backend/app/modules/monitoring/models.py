from datetime import date
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.agreements.models import new_id, utcnow


MONITORING_STATUSES = ("awaiting_setup", "upcoming", "due", "awaiting_evidence", "submitted", "reviewed", "not_assessed", "not_applicable")
_STATUS_SQL = ", ".join(f"'{status}'" for status in MONITORING_STATUSES)


class MonitoringPeriod(Base):
    __tablename__ = "monitoring_periods"
    __table_args__ = (
        UniqueConstraint("obligation_id", "obligation_revision_id", "period_label", name="uq_monitoring_period_identity"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="ck_monitoring_period_status"),
        CheckConstraint("period_end >= period_start", name="ck_monitoring_period_date_order"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False, index=True)
    obligation_revision_id: Mapped[str] = mapped_column(ForeignKey("obligation_revisions.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(String(100), nullable=False)
    fiscal_year_end: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    deadline_rule: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="awaiting_setup")
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class MonitoringUpdate(Base):
    __tablename__ = "monitoring_updates"
    __table_args__ = (CheckConstraint(f"status IN ({_STATUS_SQL})", name="ck_monitoring_update_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    monitoring_period_id: Mapped[str] = mapped_column(ForeignKey("monitoring_periods.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    supporting_reference: Mapped[str | None] = mapped_column(String(500))
    evidence_received_at: Mapped[date | None] = mapped_column(Date)
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
