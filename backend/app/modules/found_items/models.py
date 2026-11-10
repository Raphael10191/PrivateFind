from datetime import datetime

from sqlalchemy import Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow
from app.core.schema import db_enum


class DepositSession(Base):
    __tablename__ = "deposit_session"
    id: Mapped[int] = mapped_column("session_id", primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("locker.locker_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    status: Mapped[str] = mapped_column(db_enum("active", "completed", "expired"), default="active")


class FoundItem(Base):
    __tablename__ = "found_item"
    id: Mapped[int] = mapped_column("item_id", primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("deposit_session.session_id"), unique=True
    )
    compartment_id: Mapped[int | None] = mapped_column(
        ForeignKey("compartment.compartment_id"), index=True
    )
    category: Mapped[str | None] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column("finder_note", Text)
    found_at: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(
        db_enum("awaiting_deposit", "open", "reserved", "returned", "expired"),
        default="awaiting_deposit",
        index=True,
    )
    ai_status: Mapped[str] = mapped_column(db_enum("pending", "done", "failed"), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Backend additions keep direct deposits, AI retries and existing page responses.
    locker_id: Mapped[int | None] = mapped_column(ForeignKey("locker.locker_id"))
    finder_contact: Mapped[str | None] = mapped_column(String(200))
    ai_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    ai_error: Mapped[str | None] = mapped_column(String(500))
    public_summary: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list["ItemPhoto"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    attributes: Mapped[list["ItemAttribute"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )

    def attr(self, name: str) -> str | None:
        names = {name, "colour"} if name == "color" else {name}
        return next((a.value for a in self.attributes if a.name in names), None)

    def private_attributes(self) -> list["ItemAttribute"]:
        return [a for a in self.attributes if a.visibility == "private"]


class ItemPhoto(Base):
    __tablename__ = "item_photo"
    id: Mapped[int] = mapped_column("photo_id", primary_key=True)
    found_item_id: Mapped[int] = mapped_column(
        "item_id", ForeignKey("found_item.item_id"), index=True
    )
    file_name: Mapped[str] = mapped_column("storage_path", String(255))
    created_at: Mapped[datetime] = mapped_column("uploaded_at", default=utcnow)


class ItemAttribute(Base):
    __tablename__ = "item_attribute"
    id: Mapped[int] = mapped_column("attribute_id", primary_key=True)
    found_item_id: Mapped[int] = mapped_column(
        "item_id", ForeignKey("found_item.item_id"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)
    visibility: Mapped[str] = mapped_column(db_enum("public", "private"))
    weight: Mapped[int] = mapped_column(SmallInteger, default=1)
    source: Mapped[str] = mapped_column(db_enum("ai", "admin", "finder"), default="ai")

    @property
    def strength(self) -> str:
        return {1: "generic", 2: "distinctive", 3: "strong"}[self.weight or 1]

    @strength.setter
    def strength(self, value: str | None) -> None:
        self.weight = {None: 1, "generic": 1, "distinctive": 2, "strong": 3}[value]
