from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.schema import db_enum


class LostReport(Base):
    __tablename__ = "lost_report"
    id: Mapped[int] = mapped_column("report_id", primary_key=True)
    owner_id: Mapped[int] = mapped_column("user_id", ForeignKey("user.user_id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(120))
    lost_at: Mapped[datetime] = mapped_column("lost_from")
    lost_to: Mapped[datetime] = mapped_column()
    brand_model: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    unique_marks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(db_enum("open", "resolved", "closed"), default="open")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    color: Mapped[str | None] = mapped_column(String(20))
    brand: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
