import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, not_found
from app.modules.found_items.models import (
    ACTIVE_ITEM_STATUSES,
    DepositSession,
    FoundItem,
    ItemAttribute,
    ItemPhoto,
)
from app.modules.locker import service as locker_service
from app.modules.locker.models import Locker
from app.shared import audit, storage
from app.shared.ai.provider import AIError, Photo, get_ai_provider
from app.shared.ai.readiness import OFFLINE_MESSAGE, mark_ai_unavailable
from app.shared.ai.schemas import Extraction

log = logging.getLogger(__name__)
AI_TIMEOUT_S = 30

# ---------- finder deposit ----------


async def submit_deposit(
    session: AsyncSession,
    locker_code: str,
    location: str,
    note: str,
    finder_contact: str | None,
    photos: list[tuple[bytes, str | None]],
) -> tuple[FoundItem, locker_service.IssuedCode]:
    locker, item = await _new_deposit(session, locker_code, location, note, finder_contact, photos)
    issued = await _reserve_deposit(session, locker, item)
    return item, issued


async def _new_deposit(session, locker_code, location, note, finder_contact, photos):
    settings = get_settings()
    if not 1 <= len(photos) <= settings.max_photos:
        raise AppError(422, "invalid_photo", f"Upload 1 to {settings.max_photos} photos.")
    if location not in settings.locations:
        raise AppError(422, "invalid_location", "Unknown location.")

    locker = await locker_service.get_locker(session, locker_code)
    if await locker_service.free_compartments(session, locker.id) == 0:
        raise AppError(409, "compartment_unavailable", "No free compartment in this locker.")

    file_names = []
    try:
        for data, content_type in photos:
            file_names.append(storage.save_photo(data, content_type))
    except Exception:
        for name in file_names:
            storage.photo_path(name).unlink(missing_ok=True)
        raise
    item = FoundItem(
        locker_id=locker.id,
        location=location,
        note=note,
        finder_contact=finder_contact or None,
        photos=[ItemPhoto(file_name=n) for n in file_names],
    )
    session.add(item)
    await session.flush()
    return locker, item


async def _reserve_deposit(session, locker, item):
    issued = await locker_service.reserve_for_deposit(session, locker, item.id)
    audit.log(
        session,
        "item_submitted",
        "found_item",
        item.id,
        actor_type="finder",
        compartment=issued.compartment,
    )
    await session.commit()
    return issued


async def create_draft(session, locker_code, location, note, finder_contact, photos):
    await purge_expired_drafts(session)
    locker, item = await _new_deposit(session, locker_code, location, note, finder_contact, photos)
    token = secrets.token_urlsafe(32)
    draft = DepositSession(
        locker_id=locker.id,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(minutes=20),
    )
    session.add(draft)
    await session.flush()
    item.session_id = draft.id
    await session.commit()
    return item, token


async def read_draft(session, item_id: int, token: str, *, lock: bool = False):
    query = (
        select(DepositSession)
        .join(FoundItem, FoundItem.session_id == DepositSession.id)
        .where(
            FoundItem.id == item_id,
            DepositSession.token_hash == sha256(token.encode()).hexdigest(),
            DepositSession.status == "active",
            DepositSession.expires_at > utcnow(),
        )
    )
    draft = await session.scalar(query.with_for_update() if lock else query)
    if draft is None:
        raise not_found("Photo review")
    item = await get_item(session, item_id)
    if item.status != "awaiting_deposit" or item.compartment_id is not None:
        raise not_found("Photo review")
    return draft, item


async def confirm_draft(session, item_id: int, token: str, category: str | None):
    draft, item = await read_draft(session, item_id, token, lock=True)
    if item.ai_status == "pending":
        raise AppError(409, "analysis_pending", "Wait for the photo check to finish.")
    if item.ai_status == "failed":
        raise AppError(503, "ai_unavailable", OFFLINE_MESSAGE)
    if category is not None:
        item.attributes = [a for a in item.attributes if a.name != "category"]
        item.category = category
        item.attributes.append(
            ItemAttribute(
                name="category",
                value=category,
                visibility="private",
                source="finder",
                confidence=1.0,
                observation_state="observed",
            )
        )
    locker = await session.get(Locker, draft.locker_id)
    draft.status = "completed"
    return await _reserve_deposit(session, locker, item)


async def retry_draft(session, item_id: int, token: str) -> None:
    _, item = await read_draft(session, item_id, token, lock=True)
    if item.ai_status != "failed":
        raise AppError(
            409, "analysis_not_failed", "The photo check is already running or complete."
        )
    item.ai_status = "pending"
    item.ai_error = None
    await session.commit()


async def discard_draft(session, item_id: int, token: str) -> None:
    draft, item = await read_draft(session, item_id, token, lock=True)
    await _expire_drafts(session, [(draft, item)])


async def purge_expired_drafts(session: AsyncSession) -> None:
    rows = await session.execute(
        select(DepositSession, FoundItem)
        .join(FoundItem, FoundItem.session_id == DepositSession.id)
        .where(
            DepositSession.status == "active",
            DepositSession.expires_at <= utcnow(),
            FoundItem.compartment_id.is_(None),
        )
        .with_for_update()
    )
    await _expire_drafts(session, rows.all())


async def _expire_drafts(session, rows) -> None:
    paths = []
    for draft, item in rows:
        draft.status = "expired"
        item.status = "expired"
        paths.extend(photo.file_name for photo in item.photos)
        item.photos.clear()
    await session.commit()
    for name in paths:
        storage.photo_path(name).unlink(missing_ok=True)


# ---------- AI extraction (background, with retry) ----------

_tasks: set[asyncio.Task] = set()


async def run_extraction(item_id: int) -> None:
    """Extract attributes with up to N attempts and exponential backoff. Uses its own session."""
    from app.modules.matching.service import refresh_for_item

    settings = get_settings()
    ai = get_ai_provider()
    async with db.SessionLocal() as session:
        item = await session.get(FoundItem, item_id)
        if item is None or item.status == "expired" or item.ai_status != "pending":
            return
        for attempt in range(1, settings.ai_max_attempts + 1):
            await session.commit()
            try:
                photos = [Photo(storage.read_photo(p.file_name)) for p in item.photos]
                extraction = await asyncio.wait_for(
                    ai.extract_attributes(photos, item.note or ""),
                    max(AI_TIMEOUT_S, settings.qwen_timeout + 1)
                    if settings.ai_provider == "qwen"
                    else AI_TIMEOUT_S,
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure is retried
                if isinstance(exc, (AIError, TimeoutError)):
                    mark_ai_unavailable()
                log.warning(
                    "AI extraction failed for item %s (attempt %s): %s", item_id, attempt, exc
                )
                await session.refresh(
                    item, ["status", "ai_status", "ai_attempts"], with_for_update=True
                )
                if item.status == "expired" or item.ai_status != "pending":
                    return
                item.ai_attempts += 1
                item.ai_error = str(exc)[:500] or exc.__class__.__name__
                if attempt == settings.ai_max_attempts:
                    item.ai_status = "failed"
                    audit.log(session, "ai_failed", "found_item", item.id, error=item.ai_error)
                    await session.commit()
                    await refresh_for_item(item_id)
                    return
                await session.commit()
                await asyncio.sleep(settings.ai_retry_base_delay_s * 4 ** (attempt - 1))
                continue
            await session.refresh(
                item, ["status", "ai_status", "ai_attempts"], with_for_update=True
            )
            if item.status == "expired" or item.ai_status != "pending":
                return
            item.ai_attempts += 1
            _apply_extraction(item, extraction)
            audit.log(
                session, "ai_extracted", "found_item", item.id, confidence=extraction.confidence
            )
            await session.commit()
            await refresh_for_item(item_id)
            return


def _apply_extraction(item: FoundItem, ex: Extraction) -> None:
    item.category = "other" if ex.observations.get("category") == "unreadable" else ex.category
    item.public_summary = item.category
    item.description = ex.description
    attrs = []
    for name in ("category", "color", "brand", "material"):
        value = getattr(ex, name)
        state = ex.observations.get(name) or ("estimated" if value else "unreadable")
        if not value or state == "unreadable":
            continue
        attrs.append(
            ItemAttribute(
                name=name,
                value=value,
                visibility="public" if name == "color" and state == "observed" else "private",
                observation_state=state,
                confidence=1.0 if state == "observed" else 0.4,
            )
        )
    if ex.model and ex.observations.get("model") == "observed":
        attrs.append(
            ItemAttribute(
                name="model",
                value=ex.model,
                visibility="private",
                observation_state="observed",
                confidence=1.0,
            )
        )
    else:
        plausible = ex.model_candidates
        less_likely = ex.less_likely_models
        if not plausible and not less_likely and ex.observations.get("model") != "unreadable":
            single_guess = ex.model or next(
                (a.value[:100] for a in ex.private_attributes if a.type == "model"), None
            )
            plausible = [single_guess] if single_guess else []
        seen = set()
        for name, options in (
            ("model_candidate", plausible),
            ("model_candidate_less_likely", less_likely),
        ):
            for option in options:
                key = option.casefold()
                if key in seen:
                    continue
                seen.add(key)
                attrs.append(
                    ItemAttribute(
                        name=name,
                        value=option,
                        visibility="private",
                        observation_state="estimated",
                    )
                )
    attrs += [
        ItemAttribute(
            name=a.type,
            value=a.value[:200],
            visibility="private",
            strength=a.strength,
            confidence=a.confidence,
        )
        for a in ex.private_attributes
        if a.type != "model"
    ]
    item.attributes = [a for a in item.attributes if a.source != "ai"] + attrs
    item.ai_status = "done"
    item.ai_error = None


def schedule_extraction(item_id: int) -> None:
    """Fire-and-forget (used at startup); request handlers use BackgroundTasks instead."""
    task = asyncio.create_task(run_extraction(item_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def requeue_pending() -> int:
    """In-memory tasks are lost on restart, so re-schedule items still waiting for AI."""
    async with db.SessionLocal() as session:
        await purge_expired_drafts(session)
        ids = list(
            await session.scalars(
                select(FoundItem.id).where(
                    FoundItem.ai_status == "pending", FoundItem.status != "expired"
                )
            )
        )
    for item_id in ids:
        schedule_extraction(item_id)
    return len(ids)


# ---------- status changes (called by locker and claims) ----------


async def mark_stored(session: AsyncSession, item_id: int) -> None:
    item = await get_item(session, item_id)
    item.status = "open"
    audit.log(session, "item_stored", "found_item", item_id, actor_type="device")


async def mark_deposit_cancelled(session: AsyncSession, item_id: int, reason: str) -> None:
    item = await get_item(session, item_id)
    item.status = "expired"
    audit.log(session, "deposit_cancelled", "found_item", item_id, reason=reason)


async def mark_returned(
    session: AsyncSession, item_id: int, *, actor_type: str = "device", actor_id: int | None = None
) -> None:
    item = await get_item(session, item_id)
    item.status = "returned"
    from app.modules.claims.models import Claim
    from app.modules.lost_reports.models import LostReport

    approved = await session.scalar(
        select(Claim).where(Claim.found_item_id == item_id, Claim.status == "approved")
    )
    if approved:
        report = await session.get(LostReport, approved.lost_report_id)
        report.status = "resolved"
    audit.log(
        session, "item_returned", "found_item", item_id, actor_type=actor_type, actor_id=actor_id
    )


async def try_reserve(session: AsyncSession, item_id: int) -> bool:
    """STORED -> RESERVED as one conditional UPDATE: only the first approved claim wins (D6)."""
    result = await session.execute(
        update(FoundItem)
        .where(FoundItem.id == item_id, FoundItem.status == "open")
        .values(status="reserved")
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


# ---------- reads for other modules ----------


async def get_item(session: AsyncSession, item_id: int) -> FoundItem:
    item = await session.get(FoundItem, item_id)
    if item is None:
        raise not_found("Item")
    return item


async def stored_items(session: AsyncSession, found_after: datetime | None) -> list[FoundItem]:
    query = select(FoundItem).where(FoundItem.status == "open").order_by(FoundItem.id)
    if found_after is not None:
        query = query.where(FoundItem.found_at >= found_after)
    return list(await session.scalars(query.execution_options(populate_existing=True)))


# ---------- admin ----------


async def remove_item(session: AsyncSession, item_id: int, admin_id: int) -> None:
    item = await get_item(session, item_id)
    compartment = await locker_service.compartment_for_item(session, item_id, lock=True)
    await session.refresh(item, ["status"], with_for_update=True)
    was_active = item.status in ACTIVE_ITEM_STATUSES
    item.status = "expired"
    await locker_service.clear_item_access(session, item_id, compartment if was_active else None)
    audit.log(
        session, "admin_item_removed", "found_item", item_id, actor_type="admin", actor_id=admin_id
    )
    await session.commit()


async def list_items(
    session: AsyncSession, status: str | None, ai_status: str | None
) -> list[FoundItem]:
    q = select(FoundItem).order_by(FoundItem.id.desc())
    if status:
        q = q.where(FoundItem.status == status)
    if ai_status:
        q = q.where(FoundItem.ai_status == ai_status)
    return list(await session.scalars(q))


async def replace_attributes(
    session: AsyncSession,
    item_id: int,
    admin_id: int,
    category: str,
    public_summary: str | None,
    attributes: list[dict],
) -> FoundItem:
    item = await get_item(session, item_id)
    item.category = category
    if public_summary is not None:
        item.public_summary = public_summary
    # Simon's evidence rows reference attributes; keep historical evidence when
    # an administrator replaces the catalogued attributes.
    from app.modules.claims.models import OwnershipEvidence

    await session.execute(
        update(OwnershipEvidence)
        .where(OwnershipEvidence.item_attribute_id.in_([a.id for a in item.attributes]))
        .values(item_attribute_id=None)
    )
    item.attributes = [ItemAttribute(**a, source="admin") for a in attributes]
    item.ai_status = "done"
    item.ai_error = None
    audit.log(
        session, "item_corrected", "found_item", item_id, actor_type="admin", actor_id=admin_id
    )
    await session.commit()
    return item


async def reset_for_retry(session: AsyncSession, item_id: int, admin_id: int) -> None:
    item = await get_item(session, item_id)
    if item.ai_status == "done":
        raise AppError(409, "ai_already_done", "Attributes already extracted.")
    item.ai_status = "pending"
    item.ai_attempts = 0
    audit.log(
        session, "ai_retry_requested", "found_item", item_id, actor_type="admin", actor_id=admin_id
    )
    await session.commit()


async def photo_file(session: AsyncSession, item_id: int, photo_id: int):
    photo = await session.get(ItemPhoto, photo_id)
    if photo is None or photo.found_item_id != item_id:
        raise not_found("Photo")
    return storage.photo_path(photo.file_name)
