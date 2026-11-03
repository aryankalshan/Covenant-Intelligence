from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.modules.agreements.models import new_id, utcnow


json_payload_type = JSON().with_variant(JSONB, "postgresql")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_version_id: Mapped[str] = mapped_column(ForeignKey("agreement_versions.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.1.0")
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False, default="covenant-extraction-v1")
    started_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_summary: Mapped[str | None] = mapped_column(String(500))
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unprocessed_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    screened_out_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_categories: Mapped[list] = mapped_column(json_payload_type, nullable=False, default=list)
    validation_findings: Mapped[list] = mapped_column(MutableList.as_mutable(JSON().with_variant(JSONB, "postgresql")), nullable=False, default=list)
    provider_metadata: Mapped[dict] = mapped_column(json_payload_type, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ExtractionCandidate(Base):
    __tablename__ = "extraction_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="awaiting_review")
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="valid")
    validation_findings: Mapped[list] = mapped_column(json_payload_type, nullable=False, default=list)
    canonical_payload: Mapped[dict] = mapped_column(json_payload_type, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@event.listens_for(ExtractionCandidate, "before_update")
def prevent_candidate_mutation(mapper, connection, target):
    raise ValueError("Extraction candidates are immutable; create a new extraction run instead.")
