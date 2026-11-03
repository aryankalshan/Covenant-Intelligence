from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.extraction import router as extraction_router
from app.api.v1 import router
from app.api.workflow import router as workflow_router
from app.core.config import CORS_ALLOWED_ORIGINS, DATABASE_URL, DEV_IDENTITIES, DEV_WORKSPACE_ID, FRONTEND_PORT, MAX_PDF_PAGES, MAX_UPLOAD_BYTES, STORAGE_DIR, validate_cors_allowed_origins
from app.db.session import build_session_factory
from app.modules.agreements.models import User, UserMembership, Workspace
from app.modules.extraction.service import openrouter_provider_factory, run_extraction_background


def seed_development_workspace(session_factory, identity_specs: dict[str, dict] | None = None) -> None:
    specs = identity_specs or DEV_IDENTITIES
    seen: set[str] = set()
    with session_factory.begin() as db:
        workspace = db.get(Workspace, DEV_WORKSPACE_ID)
        if workspace is None:
            db.add(Workspace(id=DEV_WORKSPACE_ID, name="Covenant Intelligence Development"))
        for handle, spec in specs.items():
            user_id = spec["id"]
            if user_id in seen:
                continue
            seen.add(user_id)
            user = db.get(User, user_id)
            if user is None:
                db.add(User(id=user_id, display_name=spec["name"]))
            else:
                user.display_name = spec["name"]
            membership = db.scalar(select(UserMembership).where(
                UserMembership.workspace_id == DEV_WORKSPACE_ID,
                UserMembership.user_id == user_id,
            ))
            if membership is None:
                db.add(UserMembership(workspace_id=DEV_WORKSPACE_ID, user_id=user_id, role=spec["role"]))
            else:
                membership.role = spec["role"]


def create_app(
    database_url: str = DATABASE_URL,
    storage_dir: Path = STORAGE_DIR,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    max_pdf_pages: int = MAX_PDF_PAGES,
    dev_identity_ids: dict[str, str] | None = None,
    provider_factory: Callable | None = None,
    extraction_max_chars: int | None = None,
    extraction_overlap_chars: int | None = None,
    extraction_max_chunks: int | None = None,
    cors_allowed_origins: list[str] | None = None,
) -> FastAPI:
    identities = {handle: spec["id"] for handle, spec in DEV_IDENTITIES.items()}
    if dev_identity_ids:
        identities.update(dev_identity_ids)
    cors_origins = (
        CORS_ALLOWED_ORIGINS
        if cors_allowed_origins is None
        else validate_cors_allowed_origins(cors_allowed_origins, FRONTEND_PORT)
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Schema is owned by Alembic. The application only seeds development rows after migration.
        seed_development_workspace(application.state.session_factory)
        yield

    app = FastAPI(title="Covenant Intelligence API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Dev-User"],
    )
    engine, session_factory = build_session_factory(database_url)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage_dir = Path(storage_dir)
    app.state.max_upload_bytes = max_upload_bytes
    app.state.max_pdf_pages = max_pdf_pages
    app.state.dev_identity_ids = identities
    app.state.provider_factory = provider_factory or openrouter_provider_factory
    app.state.extraction_max_chars = extraction_max_chars
    app.state.extraction_overlap_chars = extraction_overlap_chars
    app.state.extraction_max_chunks = extraction_max_chunks
    app.include_router(router)
    app.include_router(extraction_router)
    app.include_router(workflow_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
