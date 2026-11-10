import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, not_found
from app.modules.locker import policy
from app.modules.locker.models import AccessCode, Compartment, Locker
from app.shared import audit
from app.shared.ratelimit import device_code_limiter


@dataclass
class IssuedCode:
    compartment: int
    code: str
    expires_at: datetime


def hash_secret(value: str) -> str:
    """Simon's HMAC format for short locker codes."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _code_hash(code: str) -> str:
    return hash_secret(code)


# ---------- setup / lookup ----------


async def create_locker(
    session: AsyncSession,
    code: str,
    name: str,
    location: str,
    compartments: int = 1,
    device_id: str = "locker_01",
) -> tuple[Locker, str]:
    """Create a locker with its compartments. Returns the locker and its plain device key."""
    device_key = secrets.token_urlsafe(24)
    locker = Locker(
        code=code,
        name=name,
        location=location,
        device_id=device_id,
        device_key_hash=hashlib.sha256(device_key.encode()).hexdigest(),
    )
    session.add(locker)
    await session.flush()
    session.add_all(Compartment(locker_id=locker.id, number=n) for n in range(1, compartments + 1))
    await session.commit()
    return locker, device_key


async def get_locker(session: AsyncSession, code: str) -> Locker:
    locker = await session.scalar(select(Locker).where(Locker.code == code))
    if locker is None:
        raise not_found("Locker")
    return locker


async def locker_by_device_key(session: AsyncSession, device_key: str) -> Locker | None:
    return await session.scalar(
        select(Locker).where(
            Locker.device_key_hash == hashlib.sha256(device_key.encode()).hexdigest()
        )
    )


async def free_compartments(session: AsyncSession, locker_id: int) -> int:
    await release_expired(session, locker_id)
    return await session.scalar(
        select(func.count()).where(Compartment.locker_id == locker_id, Compartment.state == "free")
    )


async def compartment_for_item(session: AsyncSession, found_item_id: int) -> Compartment | None:
    from app.modules.found_items.models import FoundItem

    return await session.scalar(
        select(Compartment)
        .join(FoundItem, FoundItem.compartment_id == Compartment.id)
        .where(FoundItem.id == found_item_id)
    )


# ---------- codes ----------


async def _new_code(
    session: AsyncSession,
    compartment: Compartment,
    item_id: int,
    purpose: str,
    ttl: timedelta,
    claim_id: int | None = None,
) -> IssuedCode:
    while True:  # avoid two active codes with the same digits in one locker
        code = f"{secrets.randbelow(10**6):06d}"
        code_hash = _code_hash(code)
        clash = await session.scalar(
            select(AccessCode.id).where(
                AccessCode.code_hash == code_hash,
                AccessCode.used_at.is_(None),
                AccessCode.expires_at > utcnow(),
            )
        )
        if not clash:
            break
    expires_at = utcnow() + ttl
    session.add(
        AccessCode(
            compartment_id=compartment.id,
            found_item_id=item_id,
            purpose=purpose,
            claim_id=claim_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
    )
    return IssuedCode(compartment.number, code, expires_at)


async def reserve_for_deposit(session: AsyncSession, locker: Locker, item_id: int) -> IssuedCode:
    """Claim a FREE compartment for a new item and issue its deposit code (caller commits)."""
    await release_expired(session, locker.id)
    free = await session.scalars(
        select(Compartment)
        .where(Compartment.locker_id == locker.id, Compartment.state == "free")
        .order_by(Compartment.number)
    )
    for compartment in free:
        # Conditional update: a concurrent deposit cannot take the same compartment.
        claimed = await session.execute(
            update(Compartment)
            .where(Compartment.id == compartment.id, Compartment.state == "free")
            .values(state="deposit_reserved")
        )
        if claimed.rowcount == 1:
            from app.modules.found_items.models import FoundItem

            await session.execute(
                update(FoundItem)
                .where(FoundItem.id == item_id)
                .values(compartment_id=compartment.id)
            )
            await session.refresh(compartment)
            ttl = timedelta(minutes=get_settings().deposit_code_ttl_min)
            return await _new_code(session, compartment, item_id, "deposit", ttl)
    raise AppError(409, "compartment_unavailable", "No free compartment in this locker.")


async def issue_pickup_code(
    session: AsyncSession, item_id: int, claim_id: int | None = None
) -> IssuedCode:
    """Issue a pickup code for a stored item; older pickup codes stop working (caller commits)."""
    compartment = await compartment_for_item(session, item_id)
    if compartment is None or compartment.state not in ("occupied", "pickup_reserved"):
        raise AppError(409, "item_not_in_locker", "The item is not available in the locker.")
    await session.execute(
        update(AccessCode)
        .where(
            AccessCode.found_item_id == item_id,
            AccessCode.purpose == "pickup",
            AccessCode.used_at.is_(None),
        )
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    ttl = timedelta(hours=get_settings().pickup_code_ttl_h)
    compartment.state = "pickup_reserved"
    return await _new_code(session, compartment, item_id, "pickup", ttl, claim_id=claim_id)


async def release_expired(session: AsyncSession, locker_id: int) -> None:
    """Free compartments whose deposit code expired before the item was put in."""
    from app.modules.found_items.models import FoundItem

    rows = await session.execute(
        select(AccessCode, Compartment)
        .join(Compartment, AccessCode.compartment_id == Compartment.id)
        .join(FoundItem, AccessCode.found_item_id == FoundItem.id)
        .where(
            Compartment.locker_id == locker_id,
            Compartment.state == "deposit_reserved",
            AccessCode.purpose == "deposit",
            AccessCode.used_at.is_(None),
            AccessCode.expires_at < utcnow(),
            FoundItem.status == "awaiting_deposit",
        )
    )
    for _code, compartment in rows.all():
        await _cancel_deposit(session, compartment, reason="code_expired")


# ---------- device flows ----------


async def validate_code(session: AsyncSession, locker: Locker, code: str) -> dict:
    key = f"locker:{locker.id}"
    if device_code_limiter.blocked(key):
        return {"authorized": False, "compartment": None, "action": None}
    await release_expired(session, locker.id)

    row = await session.execute(
        select(AccessCode, Compartment)
        .join(Compartment, AccessCode.compartment_id == Compartment.id)
        .where(
            Compartment.locker_id == locker.id,
            AccessCode.code_hash == _code_hash(code),
            AccessCode.used_at.is_(None),
            AccessCode.expires_at >= utcnow(),
        )
    )
    found = row.first()
    if found is None:
        device_code_limiter.hit(key)
        audit.log(session, "code_rejected", "locker", locker.id, actor_type="device")
        await session.commit()
        return {"authorized": False, "compartment": None, "action": None}

    access, compartment = found
    if access.expires_at < utcnow():
        await session.commit()
        return {"authorized": False, "compartment": None, "action": None}

    new_state = policy.next_state_on_code(compartment.state, access.purpose)
    if new_state is None:
        await session.commit()
        return {"authorized": False, "compartment": None, "action": None}

    access.used_at = utcnow()
    compartment.state = new_state
    audit.log(
        session,
        "compartment_opened",
        "compartment",
        compartment.id,
        actor_type="device",
        purpose=access.purpose,
        found_item_id=access.found_item_id,
    )
    await session.commit()
    return {
        "authorized": True,
        "compartment": compartment.number,
        "action": access.purpose,
    }


async def report_state(session: AsyncSession, locker: Locker, number: int, occupied: bool) -> dict:
    from app.modules.found_items import service as items  # lazy: found_items also uses locker

    compartment = await session.scalar(
        select(Compartment).where(Compartment.locker_id == locker.id, Compartment.number == number)
    )
    if compartment is None:
        raise not_found("Compartment")

    item_id = await _current_item_id(session, compartment.id)
    transition = policy.next_state_on_report(compartment.state, occupied)
    if transition is None:
        return {"compartment": number, "state": compartment.state}
    new_state, event = transition

    if event == "deposit_cancelled":
        await _cancel_deposit(session, compartment, reason="empty_after_open")
    else:
        compartment.state = new_state
        if event == "deposited":
            await items.mark_stored(session, item_id)
        elif event == "picked_up":
            await items.mark_returned(session, item_id)
    audit.log(
        session,
        f"compartment_{event}",
        "compartment",
        compartment.id,
        actor_type="device",
        found_item_id=item_id,
    )
    await session.commit()
    return {"compartment": number, "state": compartment.state}


async def heartbeat(session: AsyncSession, locker: Locker) -> datetime:
    locker.last_seen_at = utcnow()
    await session.commit()
    return locker.last_seen_at


async def _cancel_deposit(session: AsyncSession, compartment: Compartment, reason: str) -> None:
    from app.modules.found_items import service as items

    item_id = await _current_item_id(session, compartment.id)
    compartment.state = "free"
    if item_id is not None:
        await items.mark_deposit_cancelled(session, item_id, reason)


async def _current_item_id(session: AsyncSession, compartment_id: int) -> int | None:
    from app.modules.found_items.models import FoundItem

    return await session.scalar(
        select(FoundItem.id).where(
            FoundItem.compartment_id == compartment_id,
            FoundItem.status.in_(["awaiting_deposit", "open", "reserved"]),
        )
    )
