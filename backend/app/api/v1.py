import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_dev_membership, get_db, require_roles
from app.modules.audit.service import record_audit
from app.modules.agreements.models import Agreement, AgreementVersion, DocumentPage, User, UserMembership, new_id
from app.modules.documents.schemas import AgreementCreate, AgreementOut, PageOut, PageSummary, VersionOut
from app.modules.documents.service import InvalidPDF, process_version, validate_and_store_pdf

router = APIRouter(prefix="/api/v1")


def identity(db: Session, request: Request, x_dev_user: str | None) -> tuple[User, UserMembership]:
    return current_dev_membership(db, x_dev_user, request.app.state.dev_identity_ids)


def scoped_agreement(db: Session, agreement_id: str, workspace_id: str) -> Agreement:
    agreement = db.scalar(select(Agreement).where(
        Agreement.id == agreement_id,
        Agreement.workspace_id == workspace_id,
    ))
    if agreement is None:
        raise HTTPException(status_code=404, detail="Agreement not found.")
    return agreement


def scoped_version(db: Session, version_id: str, workspace_id: str) -> AgreementVersion:
    version = db.scalar(select(AgreementVersion).join(Agreement).where(
        AgreementVersion.id == version_id,
        Agreement.workspace_id == workspace_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    return version


@router.post("/agreements", response_model=AgreementOut, status_code=201)
def create_agreement(body: AgreementCreate, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    user, membership = identity(db, request, x_dev_user)
    require_roles(membership, {"admin", "contributor"})
    agreement = Agreement(
        id=new_id(), workspace_id=membership.workspace_id, name=body.name.strip(),
        counterparty=body.counterparty, created_by=user.id,
    )
    db.add(agreement)
    db.flush()
    record_audit(db, workspace_id=membership.workspace_id, actor_user_id=user.id, action="agreement_created",
                 entity_type="agreement", entity_id=agreement.id, request_id=request.headers.get("X-Request-ID"), summary={"status": "created"})
    db.commit()
    db.refresh(agreement)
    return agreement


@router.get("/agreements", response_model=list[AgreementOut])
def list_agreements(request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    return list(db.scalars(select(Agreement).where(Agreement.workspace_id == membership.workspace_id).order_by(Agreement.created_at.desc())))


@router.get("/agreements/{agreement_id}", response_model=AgreementOut)
def get_agreement(agreement_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    return scoped_agreement(db, agreement_id, membership.workspace_id)


@router.post("/agreements/{agreement_id}/versions", response_model=VersionOut, status_code=201)
async def upload_version(
    agreement_id: str,
    request: Request,
    file: UploadFile = File(...),
    version_label: str = Form(default="Original"),
    source_kind: str = Form(default="synthetic"),
    x_dev_user: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user, membership = identity(db, request, x_dev_user)
    require_roles(membership, {"admin", "contributor"})
    scoped_agreement(db, agreement_id, membership.workspace_id)
    if source_kind not in {"public", "synthetic"}:
        raise HTTPException(status_code=422, detail="source_kind must be public or synthetic.")
    max_bytes = request.app.state.max_upload_bytes
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="PDF exceeds the configured upload limit.")
    try:
        key, page_count = validate_and_store_pdf(data, file.filename or "agreement.pdf", request.app.state.storage_dir, request.app.state.max_pdf_pages)
    except InvalidPDF as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    version = AgreementVersion(
        id=new_id(), agreement_id=agreement_id, version_label=version_label,
        source_kind=source_kind, original_filename=Path(file.filename or "agreement.pdf").name[:300],
        sha256=hashlib.sha256(data).hexdigest(), storage_key=key,
        mime_type="application/pdf", size_bytes=len(data), page_count=page_count,
        status="uploaded", uploaded_by=user.id,
    )
    try:
        db.add(version)
        db.flush()
        record_audit(db, workspace_id=membership.workspace_id, actor_user_id=user.id, action="document_uploaded",
                     entity_type="agreement_version", entity_id=version.id, request_id=request.headers.get("X-Request-ID"), summary={"status": "uploaded"})
        db.commit()
        db.refresh(version)
    except Exception:
        db.rollback()
        (request.app.state.storage_dir / key).unlink(missing_ok=True)
        raise
    return version


@router.get("/agreements/{agreement_id}/versions", response_model=list[VersionOut])
def list_versions(agreement_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    scoped_agreement(db, agreement_id, membership.workspace_id)
    return list(db.scalars(select(AgreementVersion).where(AgreementVersion.agreement_id == agreement_id).order_by(AgreementVersion.uploaded_at.desc())))


@router.get("/agreements/{agreement_id}/versions/{version_id}", response_model=VersionOut)
def get_version(agreement_id: str, version_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    scoped_agreement(db, agreement_id, membership.workspace_id)
    version = db.scalar(select(AgreementVersion).where(
        AgreementVersion.id == version_id,
        AgreementVersion.agreement_id == agreement_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    return version


@router.post("/versions/{version_id}/process", status_code=200)
def process_pdf(version_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    require_roles(membership, {"admin", "contributor"})
    version = scoped_version(db, version_id, membership.workspace_id)
    file_path = request.app.state.storage_dir / version.storage_key
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Stored PDF is missing.")
    try:
        pages = process_version(db, version, file_path, request.app.state.max_pdf_pages)
        record_audit(db, workspace_id=membership.workspace_id, actor_user_id=version.uploaded_by, action="document_processed",
                     entity_type="agreement_version", entity_id=version.id, request_id=request.headers.get("X-Request-ID"), summary={"status": "processed"})
        db.commit()
    except InvalidPDF as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="PDF processing failed.")
    return {"version_id": version.id, "status": version.status, "page_count": version.page_count, "warnings": [warning for page in pages for warning in json.loads(page.warnings)]}


@router.get("/versions/{version_id}/pages", response_model=list[PageSummary])
def list_pages(version_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    version = scoped_version(db, version_id, membership.workspace_id)
    pages = db.scalars(select(DocumentPage).where(DocumentPage.agreement_version_id == version.id).order_by(DocumentPage.page_number))
    return [PageSummary(page_number=p.page_number, has_text=bool(p.text.strip()), text_sha256=p.text_sha256, warnings=json.loads(p.warnings)) for p in pages]


@router.get("/versions/{version_id}/pages/{page_number}", response_model=PageOut)
def get_page(version_id: str, page_number: int, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    version = scoped_version(db, version_id, membership.workspace_id)
    page = db.scalar(select(DocumentPage).where(
        DocumentPage.agreement_version_id == version.id,
        DocumentPage.page_number == page_number,
    ))
    if page is None:
        raise HTTPException(status_code=404, detail="Extracted page not found.")
    return PageOut(page_number=page.page_number, has_text=bool(page.text.strip()), text_sha256=page.text_sha256, warnings=json.loads(page.warnings), text=page.text)


@router.get("/versions/{version_id}/pdf")
def get_original_pdf(version_id: str, request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None)):
    _, membership = identity(db, request, x_dev_user)
    version = scoped_version(db, version_id, membership.workspace_id)
    file_path = request.app.state.storage_dir / version.storage_key
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Stored PDF is missing.")
    return FileResponse(file_path, media_type="application/pdf", filename=version.original_filename)
