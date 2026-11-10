from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.schema import db_enum


class Locker(Base):
    __tablename__ = "locker"
    id: Mapped[int] = mapped_column("locker_id", primary_key=True)
    device_id: Mapped[str] = mapped_column(String(50), unique=True)
    device_key_hash: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(120))
    last_seen_at: Mapped[datetime | None] = mapped_column()
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str | None] = mapped_column(String(100))


class Compartment(Base):
    __tablename__ = "compartment"
    __table_args__ = (UniqueConstraint("locker_id", "number"),)
    id: Mapped[int] = mapped_column("compartment_id", primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("locker.locker_id"))
    number: Mapped[int] = mapped_column(SmallInteger)
    state: Mapped[str] = mapped_column(
        db_enum(
            "free", "deposit_reserved", "deposit_open", "occupied", "pickup_reserved", "pickup_open"
        ),
        default="free",
    )


class AccessCode(Base):
    __tablename__ = "access_code"
    id: Mapped[int] = mapped_column("code_id", primary_key=True)
    compartment_id: Mapped[int] = mapped_column(
        ForeignKey("compartment.compartment_id"), index=True
    )
    found_item_id: Mapped[int] = mapped_column(
        "item_id", ForeignKey("found_item.item_id"), index=True
    )
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claim.claim_id"))
    purpose: Mapped[str] = mapped_column("type", db_enum("deposit", "pickup"))
    code_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column()
