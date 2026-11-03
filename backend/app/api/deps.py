from fastapi import HTTPException, Request
from sqlalchemy import select

from app.modules.agreements.models import User, UserMembership


def get_db(request: Request):
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_dev_membership(db, handle: str | None, identity_ids: dict[str, str]) -> tuple[User, UserMembership]:
    if not handle or handle not in identity_ids:
        raise HTTPException(status_code=401, detail="Select a seeded development identity using X-Dev-User.")
    user = db.get(User, identity_ids[handle])
    if user is None:
        raise HTTPException(status_code=401, detail="Development identity is unavailable.")
    memberships = list(db.scalars(select(UserMembership).where(UserMembership.user_id == user.id)))
    if len(memberships) != 1:
        raise HTTPException(status_code=403, detail="Workspace access denied.")
    return user, memberships[0]


def require_roles(membership: UserMembership, allowed: set[str]) -> None:
    if membership.role not in allowed:
        raise HTTPException(status_code=403, detail="This development role cannot perform that operation.")
