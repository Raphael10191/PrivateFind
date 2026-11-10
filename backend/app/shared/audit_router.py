from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.modules.identity.deps import AdminUser, SessionDep
from app.shared.audit import AuditLog

router = APIRouter(tags=["admin"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_type: str
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    details: dict | None


@router.get("/api/admin/audit", response_model=list[AuditOut])
async def audit_log(
    _: AdminUser,
    session: SessionDep,
    limit: int = Query(100, ge=1, le=1000),
    entity_type: str | None = None,
    entity_id: int | None = None,
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    return list(await session.scalars(q))
