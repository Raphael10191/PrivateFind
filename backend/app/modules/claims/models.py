from datetime import datetime

from sqlalchemy import Float, ForeignKey, SmallInteger, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow
from app.core.schema import db_enum
from app.modules.matching.models import MatchCandidate


class Claim(Base):
    __tablename__ = "claim"
    id: Mapped[int] = mapped_column("claim_id", primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_candidate.match_id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id"), index=True)
    status: Mapped[str] = mapped_column(
        db_enum("pending", "approved", "in_review", "rejected"), default="pending"
    )
    ownership_score: Mapped[float | None] = mapped_column(Float)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    decided_by: Mapped[int | None] = mapped_column("reviewed_by", ForeignKey("user.user_id"))
    decided_at: Mapped[datetime | None] = mapped_column("reviewed_at")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    critical_conflict: Mapped[bool] = mapped_column(default=False, server_default="0")
    decision_note: Mapped[str | None] = mapped_column(String(500))
    match_candidate: Mapped[MatchCandidate] = relationship(lazy="selectin")
    evidence: Mapped[list["OwnershipEvidence"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )

    @hybrid_property
    def found_item_id(self):
        return self.match_candidate.found_item_id

    @found_item_id.expression
    def found_item_id(cls):
        from sqlalchemy import select

        return (
            select(MatchCandidate.found_item_id)
            .where(MatchCandidate.id == cls.match_id)
            .scalar_subquery()
        )

    @property
    def lost_report_id(self):
        return self.match_candidate.lost_report_id


class OwnershipEvidence(Base):
    __tablename__ = "ownership_evidence"
    id: Mapped[int] = mapped_column("evidence_id", primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.claim_id"), index=True)
    item_attribute_id: Mapped[int | None] = mapped_column(
        "matched_attribute_id", ForeignKey("item_attribute.attribute_id")
    )
    type: Mapped[str] = mapped_column("detail_type", String(40))
    value: Mapped[str] = mapped_column("claimed_value", String(255))
    is_critical: Mapped[bool] = mapped_column(default=False)
    similarity: Mapped[float | None] = mapped_column("comparison_score", Float)
    result: Mapped[str] = mapped_column(
        db_enum("match", "mismatch", "not_verifiable"), default="not_verifiable"
    )
