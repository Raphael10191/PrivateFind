from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, not_found
from app.modules.claims import policy
from app.modules.claims.models import Claim, OwnershipEvidence
from app.modules.found_items import service as items
from app.modules.locker import service as locker_service
from app.modules.lost_reports import service as reports
from app.modules.matching import service as matching
from app.modules.matching.models import MatchCandidate
from app.shared import audit
from app.shared.ai.provider import get_ai_provider
from app.shared.vocab import CRITICAL_TYPES

# ---------- owner ----------


async def submit(
    session: AsyncSession, user_id: int, report_id: int, item_id: int, evidence: list[dict]
) -> tuple[Claim, locker_service.IssuedCode | None]:
    report = await reports.get_own(session, report_id, user_id)
    item = await items.get_item(session, item_id)
    if not await matching.was_shown(session, report.id, item.id):
        raise AppError(409, "not_a_candidate", "This item is not a candidate for your report.")
    if item.status != "open":
        raise AppError(409, "item_unavailable", "This item is no longer available.")
    await _check_attempts(session, user_id, item_id)

    attrs = [policy.Attr(a.id, a.name, a.value, a.strength) for a in item.private_attributes()]
    ev = [policy.Evidence(e["type"], e["value"]) for e in evidence]
    verdict = policy.verify(item.category, attrs, ev, await _similarities(attrs, ev))

    claim = Claim(
        user_id=user_id,
        match_candidate=await session.get(
            MatchCandidate, await matching.shown_match_id(session, report.id, item.id)
        ),
        status=verdict.decision,
        ownership_score=verdict.score,
        critical_conflict=verdict.critical_conflict,
        decided_at=utcnow() if verdict.decision != "in_review" else None,
        evidence=[
            OwnershipEvidence(
                type=e.type,
                value=e.value,
                result={"unmatched": "not_verifiable", "conflict": "mismatch"}.get(
                    verdict.results[i][0], verdict.results[i][0]
                ),
                is_critical=e.type in CRITICAL_TYPES,
                item_attribute_id=verdict.results[i][1],
                similarity=verdict.results[i][2],
            )
            for i, e in enumerate(ev)
        ],
    )
    session.add(claim)
    await session.flush()

    issued = None
    if verdict.decision == "approved":
        issued = await _approve(session, claim)
    audit.log(
        session,
        "claim_submitted",
        "claim",
        claim.id,
        actor_type="user",
        actor_id=user_id,
        decision=claim.status,
        score=verdict.score,
        conflict=verdict.critical_conflict,
    )
    await session.commit()
    return claim, issued


async def _similarities(attrs: list[policy.Attr], ev: list[policy.Evidence]) -> dict:
    """AI similarity for each non-critical (attribute, evidence) pair of the same type."""
    ai = get_ai_provider()
    sims = {}
    for attr in attrs:
        if attr.type in CRITICAL_TYPES:
            continue
        idx = [i for i, e in enumerate(ev) if policy.comparable(attr, e)]
        if idx:
            scores = await ai.compare_texts(attr.value, [ev[i].value for i in idx])
            sims.update({(attr.id, i): s for i, s in zip(idx, scores, strict=True)})
    return sims


async def _check_attempts(session: AsyncSession, user_id: int, item_id: int) -> None:
    settings = get_settings()
    open_claim = await session.scalar(
        select(Claim.id).where(
            Claim.user_id == user_id,
            Claim.found_item_id == item_id,
            Claim.status.in_(["in_review", "approved"]),
        )
    )
    if open_claim:
        raise AppError(409, "claim_exists", "You already have an open claim for this item.")
    since = utcnow() - timedelta(hours=settings.claim_cooldown_h)
    failed = await session.scalar(
        select(func.count()).where(
            Claim.user_id == user_id,
            Claim.found_item_id == item_id,
            Claim.status == "rejected",
            Claim.created_at >= since,
        )
    )
    if failed >= settings.max_failed_claims:
        raise AppError(429, "claim_cooldown", "Too many failed attempts. Please try again later.")


async def _approve(session: AsyncSession, claim: Claim) -> locker_service.IssuedCode:
    """Reserve the item (first approval wins), close competing claims, issue the pickup code."""
    if not await items.try_reserve(session, claim.found_item_id):
        await session.rollback()
        raise AppError(409, "item_unavailable", "This item is no longer available.")
    claim.status = "approved"
    claim.decided_at = utcnow()
    competing = await session.scalars(
        select(Claim).where(
            Claim.found_item_id == claim.found_item_id,
            Claim.id != claim.id,
            Claim.status == "in_review",
        )
    )
    for other in competing:
        other.status = "rejected"
        other.decision_note = "Item was returned to another owner."
        other.decided_at = utcnow()
    return await locker_service.issue_pickup_code(session, claim.found_item_id, claim.id)


async def list_mine(session: AsyncSession, user_id: int) -> list[Claim]:
    return list(
        await session.scalars(
            select(Claim).where(Claim.user_id == user_id).order_by(Claim.id.desc())
        )
    )


async def get_own(session: AsyncSession, claim_id: int, user_id: int) -> Claim:
    claim = await session.get(Claim, claim_id)
    if claim is None or claim.user_id != user_id:
        raise not_found("Claim")
    return claim


async def new_pickup_code(
    session: AsyncSession, claim_id: int, user_id: int
) -> locker_service.IssuedCode:
    claim = await get_own(session, claim_id, user_id)
    item = await items.get_item(session, claim.found_item_id)
    if claim.status != "approved" or item.status != "reserved":
        raise AppError(409, "pickup_not_available", "No pickup is available for this claim.")
    issued = await locker_service.issue_pickup_code(session, item.id, claim.id)
    audit.log(session, "pickup_code_issued", "claim", claim.id, actor_type="user", actor_id=user_id)
    await session.commit()
    return issued


# ---------- admin ----------


async def list_by_status(session: AsyncSession, status: str | None) -> list[Claim]:
    q = select(Claim).order_by(Claim.id.desc())
    if status:
        q = q.where(Claim.status == status)
    return list(await session.scalars(q))


async def get(session: AsyncSession, claim_id: int) -> Claim:
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise not_found("Claim")
    return claim


async def decide(
    session: AsyncSession, claim_id: int, admin_id: int, decision: str, note: str | None
) -> Claim:
    claim = await get(session, claim_id)
    if claim.status != "in_review":
        raise AppError(409, "not_in_review", "Only claims in review can be decided.")
    claim.decided_by = admin_id
    claim.decision_note = note
    if decision == "approve":
        await _approve(session, claim)  # owner then requests the pickup code
    else:
        claim.status = "rejected"
        claim.decided_at = utcnow()
    audit.log(
        session,
        "claim_decided",
        "claim",
        claim.id,
        actor_type="admin",
        actor_id=admin_id,
        decision=claim.status,
    )
    await session.commit()
    return claim
