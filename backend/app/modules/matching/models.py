from datetime import datetime

from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class MatchCandidate(Base):
    __tablename__ = "match_candidate"
    __table_args__ = (UniqueConstraint("report_id", "item_id"),)
    id: Mapped[int] = mapped_column("match_id", primary_key=True)
    lost_report_id: Mapped[int] = mapped_column(
        "report_id", ForeignKey("lost_report.report_id"), index=True
    )
    found_item_id: Mapped[int] = mapped_column(
        "item_id", ForeignKey("found_item.item_id"), index=True
    )
    category: Mapped[float] = mapped_column("category_score", Float, default=0)
    location: Mapped[float] = mapped_column("location_score", Float, default=0)
    time: Mapped[float] = mapped_column("time_score", Float, default=0)
    attributes: Mapped[float] = mapped_column("attribute_score", Float, default=0)
    semantic: Mapped[float] = mapped_column("semantic_score", Float, default=0)
    total: Mapped[float] = mapped_column("total_score", Float, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    shown: Mapped[bool] = mapped_column(default=False, server_default="0")
