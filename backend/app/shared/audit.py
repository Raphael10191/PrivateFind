from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class AuditLog(Base):
    __tablename__ = "audit_log"

    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column("log_id", primary_key=True)
    at: Mapped[datetime] = mapped_column("created_at", DateTime, default=utcnow)
    actor_type: Mapped[str] = mapped_column(
        String(20), default="system", server_default="system"
    )  # user | admin | finder | device | system
    actor_id: Mapped[int | None] = mapped_column("user_id", ForeignKey("user.user_id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON, default=dict)


def log(
    session: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    *,
    actor_type: str = "system",
    actor_id: int | None = None,
    **details,
) -> None:
    """Add an audit entry to the current transaction (committed with the caller's changes)."""
    session.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )
