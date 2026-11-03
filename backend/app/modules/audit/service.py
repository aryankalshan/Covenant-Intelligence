from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent


def record_audit(db: Session, *, workspace_id: str, actor_user_id: str | None, action: str,
                 entity_type: str, entity_id: str, request_id: str | None = None,
                 summary: dict | None = None) -> AuditEvent:
    """Write only allowlisted, non-contract text metadata into the audit stream."""
    safe_summary = {key: value for key, value in (summary or {}).items() if key in {
        "decision", "status", "count", "change_type", "period_label",
        "error_code", "http_status", "error_summary",
    }}
    event = AuditEvent(workspace_id=workspace_id, actor_user_id=actor_user_id, action=action,
                       entity_type=entity_type, entity_id=entity_id, request_id=request_id,
                       summary=safe_summary)
    db.add(event)
    return event
