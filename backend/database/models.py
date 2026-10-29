"""Database models of PrivateFind.

Every class is one table from the ER diagram in the proposal (Figure 9, section 9.4).
Table and column names are the same as in the diagram.

Groups:
- People and reports:   User, LostReport
- Found items:          DepositSession, FoundItem, ItemPhoto, ItemAttribute
- Matching:             MatchCandidate
- Ownership proof:      Claim, OwnershipEvidence
- Locker:               Locker, Compartment, AccessCode
- Log:                  AuditLog

Rules from the proposal:
- Passwords, codes, session tokens and the device key are only stored as hashes.
- Private attributes (visibility = private) are only used for verification, never shown.
- match_candidate stores all five partial scores, so every Match Score can be explained.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Fixed names for keys and indexes, so Alembic migrations are the same on every laptop
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_class: type[enum.Enum]) -> Enum:
    """Stores the lowercase value ('open') in MySQL, not the Python name ('OPEN')."""
    return Enum(
        enum_class,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
        validate_strings=True,
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Allowed values (status fields)
# ---------------------------------------------------------------------------

class UserRole(enum.Enum):
    OWNER = "owner"            # normal account: reports lost items, makes claims
    ADMIN = "admin"            # reviews unclear claims, corrects item data
    # Finders need no account. They come in through the QR code (deposit_session).


class LostReportStatus(enum.Enum):
    OPEN = "open"              # still searching
    RESOLVED = "resolved"      # item was returned
    CLOSED = "closed"          # closed by the owner or expired


class FoundItemStatus(enum.Enum):
    AWAITING_DEPOSIT = "awaiting_deposit"  # reported, but not yet in the compartment
    OPEN = "open"                          # in the locker, can be matched
    RESERVED = "reserved"                  # first approved claim reserved it
    RETURNED = "returned"                  # picked up by the owner
    EXPIRED = "expired"                    # nobody claimed it in time


class AiStatus(enum.Enum):
    PENDING = "pending"        # waiting for the AI service
    DONE = "done"              # attributes are stored
    FAILED = "failed"          # will be retried or corrected by an admin


class Visibility(enum.Enum):
    PUBLIC = "public"          # used for matching, may appear in the candidate summary
    PRIVATE = "private"        # only for ownership verification


class AttributeSource(enum.Enum):
    AI = "ai"
    ADMIN = "admin"
    FINDER = "finder"


class ClaimStatus(enum.Enum):
    PENDING = "pending"        # evidence submitted, not decided yet
    APPROVED = "approved"      # score >= 80, no critical conflict, or approved by admin
    IN_REVIEW = "in_review"    # score 50-79 or generic item, admin decides
    REJECTED = "rejected"      # score < 50, critical mismatch or too many attempts


class EvidenceResult(enum.Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_VERIFIABLE = "not_verifiable"  # detail is not stored, counts neither for nor against


class CompartmentState(enum.Enum):
    # The six states of the state diagram (Figure 8)
    FREE = "free"
    DEPOSIT_RESERVED = "deposit_reserved"
    DEPOSIT_OPEN = "deposit_open"
    OCCUPIED = "occupied"
    PICKUP_RESERVED = "pickup_reserved"
    PICKUP_OPEN = "pickup_open"


class DepositSessionStatus(enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class AccessCodeType(enum.Enum):
    DEPOSIT = "deposit"
    PICKUP = "pickup"


# ---------------------------------------------------------------------------
# People and reports
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "user"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole), default=UserRole.OWNER)
    created_at: Mapped[datetime] = created_at_column()

    lost_reports: Mapped[list["LostReport"]] = relationship(back_populates="user")
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="user", foreign_keys="Claim.user_id"
    )


class LostReport(Base):
    __tablename__ = "lost_report"

    report_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(120))
    lost_from: Mapped[datetime] = mapped_column(DateTime)
    lost_to: Mapped[datetime] = mapped_column(DateTime)
    brand_model: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    unique_marks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LostReportStatus] = mapped_column(
        enum_column(LostReportStatus), default=LostReportStatus.OPEN
    )
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped["User"] = relationship(back_populates="lost_reports")
    match_candidates: Mapped[list["MatchCandidate"]] = relationship(back_populates="lost_report")


# ---------------------------------------------------------------------------
# Found items
# ---------------------------------------------------------------------------

class DepositSession(Base):
    """Short finder session after scanning the QR code at one locker."""

    __tablename__ = "deposit_session"

    session_id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("locker.locker_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[DepositSessionStatus] = mapped_column(
        enum_column(DepositSessionStatus), default=DepositSessionStatus.ACTIVE
    )

    locker: Mapped["Locker"] = relationship(back_populates="deposit_sessions")
    found_item: Mapped["FoundItem | None"] = relationship(back_populates="deposit_session")


class FoundItem(Base):
    __tablename__ = "found_item"

    item_id: Mapped[int] = mapped_column(primary_key=True)
    # One session creates at most one item (unique)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("deposit_session.session_id"), unique=True
    )
    # A compartment keeps its old items as history, so this is not unique
    compartment_id: Mapped[int | None] = mapped_column(
        ForeignKey("compartment.compartment_id"), index=True
    )
    category: Mapped[str | None] = mapped_column(String(40))  # filled by the AI
    location: Mapped[str] = mapped_column(String(120))
    finder_note: Mapped[str | None] = mapped_column(Text)
    found_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[FoundItemStatus] = mapped_column(
        enum_column(FoundItemStatus), default=FoundItemStatus.AWAITING_DEPOSIT, index=True
    )
    ai_status: Mapped[AiStatus] = mapped_column(enum_column(AiStatus), default=AiStatus.PENDING)
    created_at: Mapped[datetime] = created_at_column()

    deposit_session: Mapped["DepositSession | None"] = relationship(back_populates="found_item")
    compartment: Mapped["Compartment | None"] = relationship(back_populates="found_items")
    photos: Mapped[list["ItemPhoto"]] = relationship(back_populates="found_item")
    attributes: Mapped[list["ItemAttribute"]] = relationship(back_populates="found_item")
    match_candidates: Mapped[list["MatchCandidate"]] = relationship(back_populates="found_item")


class ItemPhoto(Base):
    """1 to 3 photos per item. Only the path is stored, the file lies in a private folder."""

    __tablename__ = "item_photo"

    photo_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("found_item.item_id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    found_item: Mapped["FoundItem"] = relationship(back_populates="photos")


class ItemAttribute(Base):
    """One attribute of an item, e.g. name='colour', value='black'."""

    __tablename__ = "item_attribute"

    attribute_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("found_item.item_id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)  # 0.0-1.0 from the AI, empty if admin
    visibility: Mapped[Visibility] = mapped_column(enum_column(Visibility))
    weight: Mapped[int] = mapped_column(SmallInteger, default=1)  # 3 strong, 2 distinctive, 1 generic
    source: Mapped[AttributeSource] = mapped_column(
        enum_column(AttributeSource), default=AttributeSource.AI
    )

    found_item: Mapped["FoundItem"] = relationship(back_populates="attributes")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

class MatchCandidate(Base):
    """Links a lost report with a found item. All scores are 0-100."""

    __tablename__ = "match_candidate"
    __table_args__ = (UniqueConstraint("report_id", "item_id"),)

    match_id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("lost_report.report_id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("found_item.item_id"), index=True)
    category_score: Mapped[float] = mapped_column(Float, default=0)
    location_score: Mapped[float] = mapped_column(Float, default=0)
    time_score: Mapped[float] = mapped_column(Float, default=0)
    attribute_score: Mapped[float] = mapped_column(Float, default=0)
    semantic_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = created_at_column()

    lost_report: Mapped["LostReport"] = relationship(back_populates="match_candidates")
    found_item: Mapped["FoundItem"] = relationship(back_populates="match_candidates")
    claims: Mapped[list["Claim"]] = relationship(back_populates="match_candidate")


# ---------------------------------------------------------------------------
# Ownership proof
# ---------------------------------------------------------------------------

class Claim(Base):
    __tablename__ = "claim"

    claim_id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_candidate.match_id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id"), index=True)
    status: Mapped[ClaimStatus] = mapped_column(enum_column(ClaimStatus), default=ClaimStatus.PENDING)
    ownership_score: Mapped[float | None] = mapped_column(Float)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, default=1)  # max. 3 failed attempts
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("user.user_id"))  # admin
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = created_at_column()

    match_candidate: Mapped["MatchCandidate"] = relationship(back_populates="claims")
    # Two links to user: the claimant and the reviewing admin
    user: Mapped["User"] = relationship(back_populates="claims", foreign_keys=[user_id])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])
    evidence: Mapped[list["OwnershipEvidence"]] = relationship(back_populates="claim")


class OwnershipEvidence(Base):
    """One private detail the claimant gives, compared with a private item attribute."""

    __tablename__ = "ownership_evidence"

    evidence_id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.claim_id"), index=True)
    matched_attribute_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_attribute.attribute_id")
    )
    detail_type: Mapped[str] = mapped_column(String(40))  # e.g. sticker, contents, damage
    claimed_value: Mapped[str] = mapped_column(String(255))
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    comparison_score: Mapped[float | None] = mapped_column(Float)
    result: Mapped[EvidenceResult] = mapped_column(
        enum_column(EvidenceResult), default=EvidenceResult.NOT_VERIFIABLE
    )

    claim: Mapped["Claim"] = relationship(back_populates="evidence")
    matched_attribute: Mapped["ItemAttribute | None"] = relationship()


# ---------------------------------------------------------------------------
# Locker
# ---------------------------------------------------------------------------

class Locker(Base):
    __tablename__ = "locker"

    locker_id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(50), unique=True)  # identifies the ESP32
    device_key_hash: Mapped[str] = mapped_column(String(255))       # authenticates the ESP32
    location: Mapped[str] = mapped_column(String(120))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    compartments: Mapped[list["Compartment"]] = relationship(back_populates="locker")
    deposit_sessions: Mapped[list["DepositSession"]] = relationship(back_populates="locker")


class Compartment(Base):
    __tablename__ = "compartment"
    __table_args__ = (UniqueConstraint("locker_id", "number"),)

    compartment_id: Mapped[int] = mapped_column(primary_key=True)
    locker_id: Mapped[int] = mapped_column(ForeignKey("locker.locker_id"))
    number: Mapped[int] = mapped_column(SmallInteger)  # 1 or 2 in our prototype
    state: Mapped[CompartmentState] = mapped_column(
        enum_column(CompartmentState), default=CompartmentState.FREE
    )

    locker: Mapped["Locker"] = relationship(back_populates="compartments")
    found_items: Mapped[list["FoundItem"]] = relationship(back_populates="compartment")
    access_codes: Mapped[list["AccessCode"]] = relationship(back_populates="compartment")


class AccessCode(Base):
    """One-time deposit or pickup code for one compartment."""

    __tablename__ = "access_code"

    code_id: Mapped[int] = mapped_column(primary_key=True)
    compartment_id: Mapped[int] = mapped_column(
        ForeignKey("compartment.compartment_id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("found_item.item_id"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claim.claim_id"))  # only pickup codes
    type: Mapped[AccessCodeType] = mapped_column(enum_column(AccessCodeType))
    code_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)  # empty = not used yet

    compartment: Mapped["Compartment"] = relationship(back_populates="access_codes")
    found_item: Mapped["FoundItem"] = relationship()
    claim: Mapped["Claim | None"] = relationship()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

class AuditLog(Base):
    """Who did what and when. user_id is empty for actions of the system or the locker."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    log_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.user_id"))
    action: Mapped[str] = mapped_column(String(50))       # e.g. claim_approved, code_failed
    entity_type: Mapped[str] = mapped_column(String(40))  # e.g. claim, found_item, compartment
    entity_id: Mapped[int | None] = mapped_column()
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped["User | None"] = relationship()
