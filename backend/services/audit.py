"""Audit log: who did what and when (proposal FR7, NFR5)."""
from sqlalchemy.orm import Session

from backend.database.models import AuditLog


def log_action(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    user_id: int | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Adds one entry. Never store plain codes, passwords or private details here."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        details=details,
    )
    db.add(entry)
    return entry
