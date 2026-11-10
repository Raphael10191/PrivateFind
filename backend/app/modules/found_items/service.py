import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.modules.found_items.models import FoundItem, ItemAttribute, ItemPhoto
from app.modules.locker import service as locker_service
from app.shared import audit, storage
from app.shared.ai.provider import Photo, get_ai_provider
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
    settings = get_settings()
    if not 1 <= len(photos) <= settings.max_photos:
        raise AppError(422, "invalid_photo", f"Upload 1 to {settings.max_photos} photos.")
    if location not in settings.locations:
        raise AppError(422, "invalid_location", "Unknown location.")

    locker = await locker_service.get_locker(session, locker_code)
    if await locker_service.free_compartments(session, locker.id) == 0:
        raise AppError(409, "compartment_unavailable", "No free compartment in this locker.")

    file_names = [storage.save_photo(data, ctype) for data, ctype in photos]
    item = FoundItem(
        locker_id=locker.id,
        location=location,
        note=note,
        finder_contact=finder_contact or None,
        photos=[ItemPhoto(file_name=n) for n in file_names],
    )
    session.add(item)
    await session.flush()
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
    return item, issued


# ---------- AI extraction (background, with retry) ----------

_tasks: set[asyncio.Task] = set()


async def run_extraction(item_id: int) -> None:
    """Extract attributes with up to N attempts and exponential backoff. Uses its own session."""
    settings = get_settings()
    ai = get_ai_provider()
    async with db.SessionLocal() as session:
        item = await session.get(FoundItem, item_id)
        if item is None or item.ai_status == "done":
            return
        photos = [Photo(storage.read_photo(p.file_name)) for p in item.photos]

        for attempt in range(1, settings.ai_max_attempts + 1):
            item.ai_attempts += 1
            try:
                extraction = await asyncio.wait_for(
                    ai.extract_attributes(photos, item.note), AI_TIMEOUT_S
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure is retried
                log.warning(
                    "AI extraction failed for item %s (attempt %s): %s", item_id, attempt, exc
                )
                item.ai_error = str(exc)[:500] or exc.__class__.__name__
                await session.commit()
                if attempt < settings.ai_max_attempts:
                    await asyncio.sleep(settings.ai_retry_base_delay_s * 4 ** (attempt - 1))
                continue
            _apply_extraction(item, extraction)
            audit.log(
                session, "ai_extracted", "found_item", item.id, confidence=extraction.confidence
            )
            await session.commit()
            return

        item.ai_status = "failed"
        audit.log(session, "ai_failed", "found_item", item.id, error=item.ai_error)
        await session.commit()


def _apply_extraction(item: FoundItem, ex: Extraction) -> None:
    item.category = ex.category
    item.public_summary = ex.public_summary[:200]
    item.description = ex.description
    attrs = [
        ItemAttribute(name=n, value=v, visibility="public", confidence=ex.confidence)
        for n, v in (("color", ex.color), ("brand", ex.brand))
        if v
    ]
    attrs += [
        ItemAttribute(
            name=a.type,
            value=a.value[:200],
            visibility="private",
            strength=a.strength,
            confidence=a.confidence,
        )
        for a in ex.private_attributes
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
        ids = list(
            await session.scalars(select(FoundItem.id).where(FoundItem.ai_status == "pending"))
        )
    for item_id in ids:
        schedule_extraction(item_id)
    return len(ids)


# ---------- status changes (called by locker and claims) ----------


async def _get(session: AsyncSession, item_id: int) -> FoundItem:
    item = await session.get(FoundItem, item_id)
    if item is None:
        raise not_found("Item")
    return item


async def mark_stored(session: AsyncSession, item_id: int) -> None:
    item = await _get(session, item_id)
    item.status = "open"
    audit.log(session, "item_stored", "found_item", item_id, actor_type="device")


async def mark_deposit_cancelled(session: AsyncSession, item_id: int, reason: str) -> None:
    item = await _get(session, item_id)
    item.status = "expired"
    audit.log(session, "deposit_cancelled", "found_item", item_id, reason=reason)


async def mark_returned(session: AsyncSession, item_id: int) -> None:
    item = await _get(session, item_id)
    item.status = "returned"
    from app.modules.claims.models import Claim
    from app.modules.lost_reports.models import LostReport

    approved = await session.scalar(
        select(Claim).where(Claim.found_item_id == item_id, Claim.status == "approved")
    )
    if approved:
        report = await session.get(LostReport, approved.lost_report_id)
        report.status = "resolved"
    audit.log(session, "item_returned", "found_item", item_id, actor_type="device")


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
    return await _get(session, item_id)


async def stored_items(
    session: AsyncSession, category: str, found_after: datetime
) -> list[FoundItem]:
    return list(
        await session.scalars(
            select(FoundItem).where(
                FoundItem.status == "open",
                FoundItem.category == category,
                FoundItem.found_at >= found_after,
            )
        )
    )


# ---------- admin ----------


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
    item = await _get(session, item_id)
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
    item = await _get(session, item_id)
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
