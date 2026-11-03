from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)


class UserMembership(Base):
    __tablename__ = "user_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_user_membership_workspace_user"),
        CheckConstraint("role IN ('admin', 'reviewer', 'contributor', 'read_only')", name="ck_user_membership_role"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)


class Agreement(Base):
    __tablename__ = "agreements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    counterparty: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    versions: Mapped[list["AgreementVersion"]] = relationship(back_populates="agreement", order_by="AgreementVersion.uploaded_at")


class AgreementVersion(Base):
    __tablename__ = "agreement_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreements.id"), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    agreement: Mapped[Agreement] = relationship(back_populates="versions")
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="version", order_by="DocumentPage.page_number", cascade="all, delete-orphan")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("agreement_version_id", "page_number", name="uq_document_page_version_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agreement_version_id: Mapped[str] = mapped_column(ForeignKey("agreement_versions.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(30), nullable=False, default="pymupdf_text")
    warnings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[AgreementVersion] = relationship(back_populates="pages")
