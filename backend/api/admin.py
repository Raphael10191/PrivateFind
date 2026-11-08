"""Admin API: audit log and activity alerts (work package 9.2, proposal FR7).

Only users with the role "admin" may use these routes (get_current_admin).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_current_admin, get_db
from backend.database.models import AuditLog, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AuditLogOut(BaseModel):
    log_id: int
    created_at: datetime
    action: str
    entity_type: str
    entity_id: int | None
    user_id: int | None
    details: dict | None


@router.get("/audit-log", response_model=list[AuditLogOut])
def audit_log(
    only_alerts: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Newest entries first. only_alerts=true shows only the activity alerts."""
    query = select(AuditLog).order_by(AuditLog.log_id.desc()).limit(limit)
    if only_alerts:
        query = query.where(AuditLog.action.startswith("alert_"))
    return [
        AuditLogOut(
            log_id=entry.log_id,
            created_at=entry.created_at,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            user_id=entry.user_id,
            details=entry.details,
        )
        for entry in db.scalars(query)
    ]
