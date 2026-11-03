from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class AgreementCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    counterparty: str | None = Field(default=None, max_length=300)


class AgreementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    counterparty: str | None
    created_at: datetime


class VersionOut(BaseModel):
    id: str
    agreement_id: str
    version_label: str
    source_kind: str
    original_filename: str
    sha256: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: str
    uploaded_at: datetime


class PageSummary(BaseModel):
    page_number: int
    has_text: bool
    text_sha256: str
    warnings: list[str]


class PageOut(PageSummary):
    text: str
