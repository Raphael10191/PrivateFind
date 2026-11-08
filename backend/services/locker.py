"""Locker logic: one-time codes and the compartment states (support for 6.7).

The ESP32 never decides if a code is valid. It forwards the code, the backend
checks it here and answers which compartment opens (proposal 2.1).

Compartment states (state diagram, Figure 8):
    free -> deposit_reserved -> deposit_open -> occupied
         -> pickup_reserved -> pickup_open -> free
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import config
from backend.database.models import (
    AccessCode,
    AccessCodeType,
    AuditLog,
    Claim,
    ClaimStatus,
    Compartment,
    CompartmentState,
    FoundItem,
    FoundItemStatus,
    Locker,
    LostReportStatus,
)
from backend.security import hash_code, hash_token, new_numeric_code
from backend.services.audit import log_action


class LockerError(Exception):
    pass


@dataclass
class CodeCheckResult:
    authorized: bool
    compartment: int | None = None
    action: str | None = None  # "deposit" or "pickup"


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

def authenticate_device(db: Session, device_id: str, device_key: str | None) -> Locker | None:
    """Checks the device key the ESP32 sends with every request."""
    locker = db.scalar(select(Locker).where(Locker.device_id == device_id))
    if locker is None or not device_key or hash_token(device_key) != locker.device_key_hash:
        return None
    locker.last_seen_at = datetime.now()
    return locker


# ---------------------------------------------------------------------------
# Compartments
# ---------------------------------------------------------------------------

def release_expired_deposits(db: Session, locker_id: int) -> None:
    """Frees compartments whose deposit code expired before the finder used it."""
    reserved = db.scalars(
        select(Compartment).where(
            Compartment.locker_id == locker_id,
            Compartment.state == CompartmentState.DEPOSIT_RESERVED,
        )
    ).all()
    for compartment in reserved:
        if not compartment.access_codes:
            continue
        # The newest code of the compartment is the one of the current deposit
        newest_code = max(compartment.access_codes, key=lambda c: c.code_id)
        if newest_code.used_at is None and newest_code.expires_at < datetime.now():
            compartment.state = CompartmentState.FREE
            newest_code.found_item.status = FoundItemStatus.EXPIRED
            log_action(db, "deposit_expired", "compartment", compartment.compartment_id,
                       details={"item_id": newest_code.item_id})
    # The session has autoflush=False: write the changes now, so the following
    # query for a free compartment already sees them
    db.flush()


def has_free_compartment(db: Session, locker_id: int) -> bool:
    release_expired_deposits(db, locker_id)
    return db.scalar(
        select(Compartment.compartment_id).where(
            Compartment.locker_id == locker_id,
            Compartment.state == CompartmentState.FREE,
        ).limit(1)
    ) is not None


def reserve_free_compartment(db: Session, locker_id: int) -> Compartment:
    """Takes a free compartment and reserves it for a deposit.

    FOR UPDATE locks the row in MySQL, so two finders cannot get the same compartment.
    """
    release_expired_deposits(db, locker_id)
    compartment = db.scalar(
        select(Compartment)
        .where(Compartment.locker_id == locker_id, Compartment.state == CompartmentState.FREE)
        .order_by(Compartment.number)
        .limit(1)
        .with_for_update()
    )
    if compartment is None:
        raise LockerError("No free compartment.")
    compartment.state = CompartmentState.DEPOSIT_RESERVED
    return compartment


# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------

def _active_codes(db: Session, locker_id: int) -> list[AccessCode]:
    return list(
        db.scalars(
            select(AccessCode)
            .join(Compartment)
            .where(
                Compartment.locker_id == locker_id,
                AccessCode.used_at.is_(None),
                AccessCode.expires_at >= datetime.now(),
            )
        )
    )


def create_access_code(
    db: Session,
    compartment: Compartment,
    item: FoundItem,
    code_type: AccessCodeType,
    valid_for: timedelta,
    claim: Claim | None = None,
) -> str:
    """Creates a one-time code and returns it in plain text.

    The plain code is shown to the user once and never stored.
    """
    # The code must be unique among the active codes of this locker,
    # because check_code() finds the compartment by the code
    used_hashes = [c.code_hash for c in _active_codes(db, compartment.locker_id)]
    code = new_numeric_code()
    while hash_code(code) in used_hashes:
        code = new_numeric_code()

    db.add(
        AccessCode(
            compartment=compartment,
            found_item=item,
            claim=claim,
            type=code_type,
            code_hash=hash_code(code),
            expires_at=datetime.now() + valid_for,
        )
    )
    return code


def create_pickup_code(db: Session, claim: Claim) -> str:
    """For the Ownership Verification Engine (9.1): call after a claim is approved.

    Returns the plain pickup code for the owner.
    """
    item = claim.match_candidate.found_item
    compartment = item.compartment
    if compartment is None or compartment.state != CompartmentState.OCCUPIED:
        raise LockerError("The item is not in a locker compartment.")

    compartment.state = CompartmentState.PICKUP_RESERVED
    item.status = FoundItemStatus.RESERVED
    code = create_access_code(
        db, compartment, item, AccessCodeType.PICKUP,
        timedelta(hours=config.PICKUP_CODE_HOURS), claim=claim,
    )
    log_action(db, "pickup_code_created", "claim", claim.claim_id, user_id=claim.user_id,
               details={"item_id": item.item_id, "compartment": compartment.number})
    return code


def check_code(db: Session, locker: Locker, code: str) -> CodeCheckResult:
    """Called when someone types a code on the keypad and presses #.

    A valid code is used up at once (one-time code).
    """
    code_hash = hash_code(code.strip())
    match = next((c for c in _active_codes(db, locker.locker_id) if c.code_hash == code_hash), None)

    if match is None:
        # Never log the code itself, only that a wrong code was entered
        log_action(db, "code_failed", "locker", locker.locker_id)
        _alert_if_many_wrong_codes(db, locker)
        return CodeCheckResult(authorized=False)

    compartment = match.compartment
    expected_state = (
        CompartmentState.DEPOSIT_RESERVED
        if match.type == AccessCodeType.DEPOSIT
        else CompartmentState.PICKUP_RESERVED
    )
    if compartment.state != expected_state:
        log_action(db, "code_wrong_state", "compartment", compartment.compartment_id,
                   details={"state": compartment.state.value, "type": match.type.value})
        return CodeCheckResult(authorized=False)

    match.used_at = datetime.now()
    compartment.state = (
        CompartmentState.DEPOSIT_OPEN
        if match.type == AccessCodeType.DEPOSIT
        else CompartmentState.PICKUP_OPEN
    )
    log_action(db, f"{match.type.value}_code_used", "compartment", compartment.compartment_id,
               details={"item_id": match.item_id})
    return CodeCheckResult(authorized=True, compartment=compartment.number, action=match.type.value)


def _alert_if_many_wrong_codes(db: Session, locker: Locker) -> None:
    """Activity alert (8.3): someone may try to guess codes at the keypad."""
    db.flush()  # so the count below includes the wrong code from just now
    wrong_codes = db.scalar(
        select(func.count(AuditLog.log_id)).where(
            AuditLog.action == "code_failed",
            AuditLog.entity_id == locker.locker_id,
            AuditLog.created_at >= datetime.now() - timedelta(minutes=10),
        )
    )
    if wrong_codes == config.ALERT_WRONG_CODES_PER_LOCKER:
        log_action(db, "alert_many_wrong_codes", "locker", locker.locker_id,
                   details={"wrong_codes_in_10_min": wrong_codes})


# ---------------------------------------------------------------------------
# Door closed: the ESP32 reports if the sensor sees an item
# ---------------------------------------------------------------------------

def _current_item(compartment: Compartment) -> FoundItem | None:
    """The item that is (or will be) in the compartment right now."""
    for item in compartment.found_items:
        if item.status in (FoundItemStatus.AWAITING_DEPOSIT, FoundItemStatus.OPEN, FoundItemStatus.RESERVED):
            return item
    return None


def report_compartment_state(db: Session, locker: Locker, number: int, occupied: bool) -> Compartment:
    """The user closed the door and pressed #, the sensor says if an item is inside."""
    compartment = db.scalar(
        select(Compartment).where(Compartment.locker_id == locker.locker_id, Compartment.number == number)
    )
    if compartment is None:
        raise LockerError("Unknown compartment.")

    item = _current_item(compartment)
    old_state = compartment.state

    if old_state == CompartmentState.DEPOSIT_OPEN:
        if occupied:
            compartment.state = CompartmentState.OCCUPIED
            if item:
                item.status = FoundItemStatus.OPEN  # now it can be matched
        else:
            # Finder closed the door without putting the item in
            compartment.state = CompartmentState.FREE
            if item:
                item.status = FoundItemStatus.EXPIRED

    elif old_state == CompartmentState.PICKUP_OPEN:
        if not occupied:
            compartment.state = CompartmentState.FREE
            if item:
                item.status = FoundItemStatus.RETURNED
                for candidate in item.match_candidates:
                    if any(claim.status == ClaimStatus.APPROVED for claim in candidate.claims):
                        candidate.lost_report.status = LostReportStatus.RESOLVED
        else:
            # Owner did not take the item: stays inside, admin has to check
            compartment.state = CompartmentState.OCCUPIED

    log_action(db, "compartment_state", "compartment", compartment.compartment_id,
               details={"from": old_state.value, "to": compartment.state.value, "occupied": occupied,
                        "item_id": item.item_id if item else None})
    return compartment
