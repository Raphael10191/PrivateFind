"""Finder deposit and item persistence (work package 6.3).

Flow (proposal 2.1, steps 1-3):
1. The finder scans the QR code at the locker -> start_deposit_session()
2. Three photos, quick answers, location and note -> create_deposit()
   The backend stores the item, reserves the free compartment and creates a deposit code.
3. The AI service (Zohidjon, 6.5) analyses the photos later and calls save_ai_attributes().
4. The finder types the deposit code at the locker (see services/locker.py).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import config
from backend.database.models import (
    AccessCodeType,
    AiStatus,
    AttributeSource,
    Compartment,
    DepositSession,
    DepositSessionStatus,
    FoundItem,
    FoundItemStatus,
    ItemAttribute,
    ItemPhoto,
    Locker,
    Visibility,
)
from backend.security import hash_token, new_token
from backend.services import locker as locker_service
from backend.services.audit import log_action


class DepositError(Exception):
    pass


class NoFreeCompartmentError(DepositError):
    pass


@dataclass
class PhotoUpload:
    content: bytes
    content_type: str


class FinderAnswer(BaseModel):
    """Answer to one quick-select question, e.g. name='contents', value='student card'.

    Answers are private by default: they can later prove ownership.
    weight: 3 strong, 2 distinctive, 1 generic (proposal 4.4).
    """
    name: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=255)
    visibility: Visibility = Visibility.PRIVATE
    weight: int = Field(default=1, ge=1, le=3)


@dataclass
class DepositResult:
    item: FoundItem
    compartment: Compartment
    deposit_code: str  # plain code, shown to the finder once
    code_expires_at: datetime


def check_category(category: str | None) -> str | None:
    """Only categories from config.CATEGORIES are allowed (input validation, 8.2)."""
    if not category:
        return None
    category = category.strip().lower()
    if category not in config.CATEGORIES:
        raise DepositError("Unknown category.")
    return category


# ---------------------------------------------------------------------------
# Step 1: QR code -> deposit session
# ---------------------------------------------------------------------------

def start_deposit_session(db: Session, locker_id: int) -> tuple[DepositSession, str]:
    """Returns the session and the plain token (only the hash is stored)."""
    if db.get(Locker, locker_id) is None:
        raise DepositError("Unknown locker.")
    if not locker_service.has_free_compartment(db, locker_id):
        # Proposal 4.5: if no compartment is free, the QR page does not accept a deposit
        raise NoFreeCompartmentError("The locker is full at the moment.")

    token = new_token()
    session = DepositSession(
        locker_id=locker_id,
        token_hash=hash_token(token),
        expires_at=datetime.now() + timedelta(minutes=config.DEPOSIT_SESSION_MINUTES),
        status=DepositSessionStatus.ACTIVE,
    )
    db.add(session)
    db.flush()
    log_action(db, "deposit_session_started", "deposit_session", session.session_id,
               details={"locker_id": locker_id})
    return session, token


def get_active_session(db: Session, token: str) -> DepositSession:
    session = db.scalar(select(DepositSession).where(DepositSession.token_hash == hash_token(token)))
    if session is None or session.status != DepositSessionStatus.ACTIVE:
        raise DepositError("The deposit session is not valid. Please scan the QR code again.")
    if session.expires_at < datetime.now():
        raise DepositError("The deposit session has expired. Please scan the QR code again.")
    return session


# ---------------------------------------------------------------------------
# Step 2: photos, answers, location -> found item + compartment + deposit code
# ---------------------------------------------------------------------------

def _looks_like_image(content: bytes) -> bool:
    """Checks the first bytes of the file (the browser's content type can be faked)."""
    return (
        content.startswith(b"\xff\xd8\xff")                          # JPEG
        or content.startswith(b"\x89PNG")                            # PNG
        or (content[:4] == b"RIFF" and content[8:12] == b"WEBP")     # WebP
        or content[4:8] == b"ftyp"                                   # HEIC (iPhone)
    )


def check_photos(photos: list[PhotoUpload]) -> None:
    if len(photos) != config.PHOTOS_PER_ITEM:
        raise DepositError(f"Please take exactly {config.PHOTOS_PER_ITEM} photos.")
    for photo in photos:
        if photo.content_type not in config.ALLOWED_PHOTO_TYPES:
            raise DepositError("Only JPEG, PNG, WebP or HEIC photos are allowed.")
        if not photo.content:
            raise DepositError("A photo is empty.")
        if len(photo.content) > config.MAX_PHOTO_BYTES:
            raise DepositError("A photo is larger than 10 MB.")
        if not _looks_like_image(photo.content):
            raise DepositError("A file is not a real photo.")


def _save_photos(item: FoundItem, photos: list[PhotoUpload]) -> None:
    """Saves the files in the private upload folder (never public)."""
    folder = config.UPLOAD_DIR / "items" / str(item.item_id)
    folder.mkdir(parents=True, exist_ok=True)
    for photo in photos:
        # Random file name: the finder's file name is never used
        filename = uuid.uuid4().hex + config.ALLOWED_PHOTO_TYPES[photo.content_type]
        (folder / filename).write_bytes(photo.content)
        # Store the path relative to UPLOAD_DIR, so the folder can move (e.g. Docker volume)
        item.photos.append(ItemPhoto(storage_path=f"items/{item.item_id}/{filename}"))


def create_deposit(
    db: Session,
    token: str,
    location: str,
    photos: list[PhotoUpload],
    answers: list[FinderAnswer] | None = None,
    category: str | None = None,
    finder_note: str | None = None,
) -> DepositResult:
    session = get_active_session(db, token)
    check_photos(photos)
    category = check_category(category)
    if not location.strip():
        raise DepositError("Please enter where you found the item.")

    try:
        compartment = locker_service.reserve_free_compartment(db, session.locker_id)
    except locker_service.LockerError as exc:
        raise NoFreeCompartmentError(str(exc)) from exc

    item = FoundItem(
        deposit_session=session,
        compartment=compartment,
        category=category,
        location=location.strip(),
        finder_note=(finder_note or "").strip() or None,
        found_at=datetime.now(),
        status=FoundItemStatus.AWAITING_DEPOSIT,
        ai_status=AiStatus.PENDING,
    )
    db.add(item)
    db.flush()  # gives item.item_id for the photo folder

    for answer in answers or []:
        item.attributes.append(
            ItemAttribute(
                name=answer.name.strip().lower(),
                value=answer.value.strip(),
                visibility=answer.visibility,
                weight=answer.weight,
                source=AttributeSource.FINDER,
            )
        )

    code_valid_for = timedelta(minutes=config.DEPOSIT_CODE_MINUTES)
    code = locker_service.create_access_code(db, compartment, item, AccessCodeType.DEPOSIT, code_valid_for)
    session.status = DepositSessionStatus.COMPLETED
    _save_photos(item, photos)

    log_action(db, "item_deposited", "found_item", item.item_id,
               details={"compartment": compartment.number, "photos": len(photos)})
    return DepositResult(
        item=item,
        compartment=compartment,
        deposit_code=code,
        code_expires_at=datetime.now() + code_valid_for,
    )


# ---------------------------------------------------------------------------
# Step 3: results of the AI service (called by Zohidjon's AI module, 6.5)
# ---------------------------------------------------------------------------

class AiAttribute(BaseModel):
    name: str = Field(max_length=50)
    value: str = Field(max_length=255)
    confidence: float = Field(ge=0, le=1)
    visibility: Visibility
    weight: int = Field(default=1, ge=1, le=3)


class AiResult(BaseModel):
    """Answer of the AI service after the Pydantic check (proposal 9.5).

    Adjust the fields together with the AI schema from work package 4.3 if needed.
    """
    category: str | None = None
    attributes: list[AiAttribute] = []


def get_photo_paths(item: FoundItem) -> list[Path]:
    """Full file paths of the photos, e.g. to send them to the AI service."""
    return [config.UPLOAD_DIR / photo.storage_path for photo in item.photos]


def save_ai_attributes(db: Session, item_id: int, result: AiResult) -> FoundItem:
    """Replaces the old AI attributes of an item. Finder and admin attributes stay."""
    item = db.get(FoundItem, item_id)
    if item is None:
        raise DepositError("Unknown item.")

    for attribute in list(item.attributes):
        if attribute.source == AttributeSource.AI:
            item.attributes.remove(attribute)
            db.delete(attribute)

    for attribute in result.attributes:
        item.attributes.append(
            ItemAttribute(
                name=attribute.name.strip().lower(),
                value=attribute.value.strip(),
                confidence=attribute.confidence,
                visibility=attribute.visibility,
                weight=attribute.weight,
                source=AttributeSource.AI,
            )
        )

    # The AI may only set a category from our list, otherwise "other"
    if result.category:
        ai_category = result.category.strip().lower()
        item.category = ai_category if ai_category in config.CATEGORIES else "other"

    item.ai_status = AiStatus.DONE
    log_action(db, "ai_attributes_saved", "found_item", item.item_id,
               details={"count": len(result.attributes), "category": item.category})
    return item


def mark_ai_failed(db: Session, item_id: int, reason: str) -> None:
    """The AI job failed. It will be retried or corrected by an admin (proposal 4.5)."""
    item = db.get(FoundItem, item_id)
    if item is None:
        raise DepositError("Unknown item.")
    item.ai_status = AiStatus.FAILED
    log_action(db, "ai_failed", "found_item", item_id, details={"reason": reason[:200]})
