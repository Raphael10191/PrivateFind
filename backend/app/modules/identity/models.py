from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.schema import db_enum


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column("user_id", primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(db_enum("owner", "admin"), default="owner")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    display_name: Mapped[str | None] = mapped_column(String(100))
