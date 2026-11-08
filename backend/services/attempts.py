"""Growing wait times after failed claims (proposal 4.4, work package 8.3).

Rules:
- Wait times grow per account AND item: 5, 10, 20 minutes, max. 1 hour.
- Failed claims of OTHER users never make it harder for the real owner.
- There is no global lock of an item.

- Many failed claims on one item create an alert for the administrator.

The Ownership Verification Engine (9.1, Zohidjon) uses this file:
- before a claim:          claim_wait_until()  -> if not None, the user has to wait
- for a new claim:         next_attempt_no()
- after a rejected claim:  alert_if_many_failed_claims()
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import config
from backend.database.models import Claim, ClaimStatus, MatchCandidate
from backend.services.audit import log_action


def failed_claims(db: Session, user_id: int, item_id: int) -> list[Claim]:
    return list(
        db.scalars(
            select(Claim)
            .join(MatchCandidate)
            .where(
                Claim.user_id == user_id,
                MatchCandidate.item_id == item_id,
                Claim.status == ClaimStatus.REJECTED,
            )
            .order_by(Claim.created_at, Claim.claim_id)
        )
    )


def claim_wait_until(db: Session, user_id: int, item_id: int) -> datetime | None:
    """Returns until when this user has to wait for this item, or None if no wait."""
    failed = failed_claims(db, user_id, item_id)
    if not failed:
        return None
    steps = config.CLAIM_WAIT_MINUTES
    minutes = steps[min(len(failed) - 1, len(steps) - 1)]
    until = failed[-1].created_at + timedelta(minutes=minutes)
    return until if until > datetime.now() else None


def next_attempt_no(db: Session, user_id: int, item_id: int) -> int:
    """Value for Claim.attempt_no: 1 for the first claim of this user on this item."""
    return len(failed_claims(db, user_id, item_id)) + 1


def alert_if_many_failed_claims(db: Session, item_id: int) -> None:
    """Activity alert (8.3): many failed claims on one item within 24 hours.

    The alert only goes to the administrator (audit log). It never makes the check
    harder for the real owner. The admin can then block single accounts.
    """
    db.flush()  # so the count below includes the claim that was just rejected
    failed = db.scalar(
        select(func.count(Claim.claim_id))
        .join(MatchCandidate)
        .where(
            MatchCandidate.item_id == item_id,
            Claim.status == ClaimStatus.REJECTED,
            Claim.created_at >= datetime.now() - timedelta(hours=24),
        )
    )
    if failed == config.ALERT_FAILED_CLAIMS_PER_ITEM:
        log_action(db, "alert_many_failed_claims", "found_item", item_id,
                   details={"failed_claims_in_24_h": failed})
