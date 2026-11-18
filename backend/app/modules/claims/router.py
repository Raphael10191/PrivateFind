from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.claims import service
from app.modules.claims.models import Claim
from app.modules.claims.policy import MESSAGES, NEXT_ACTION_MESSAGES
from app.modules.claims.schemas import (
    AdminClaimOut,
    ClaimIn,
    ClaimOut,
    DecisionIn,
    EvidenceOut,
    PickupCodeOut,
)
from app.modules.found_items import service as items
from app.modules.found_items.models import FoundItem
from app.modules.found_items.schemas import AttributeIO
from app.modules.identity.deps import AdminUser, CurrentUser, SessionDep
from app.modules.lost_reports.models import LostReport
from app.shared.ratelimit import claim_limiter

router = APIRouter(tags=["claims"])


def _out(claim: Claim, issued=None, *, pickup_revoked: bool = False) -> ClaimOut:
    status = claim.status
    if claim.verification_state == "handed_over":
        status = "handed_over"
    elif pickup_revoked:
        status = "revoked"
    return ClaimOut(
        id=claim.id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=status,
        verification_state=claim.verification_state,
        next_action=claim.next_action,
        message=NEXT_ACTION_MESSAGES.get(claim.next_action, MESSAGES[status]),
        created_at=claim.created_at,
        compartment=issued.compartment if issued else None,
        pickup_code=issued.code if issued else None,
        pickup_expires_at=issued.expires_at if issued else None,
    )


@router.post("/api/claims", response_model=ClaimOut, status_code=201)
async def submit(body: ClaimIn, user: CurrentUser, session: SessionDep):
    if not claim_limiter.hit(str(user.id)):
        raise AppError(429, "claim_cooldown", "Too many attempts. Please try again later.")
    claim, issued = await service.submit(
        session,
        user.id,
        body.lost_report_id,
        body.found_item_id,
        [e.model_dump() for e in body.evidence or []],
        description=body.description,
    )
    return _out(claim, issued)


async def _owner_claims_out(session: AsyncSession, claims: list[Claim]) -> list[ClaimOut]:
    approved_items = {c.found_item_id for c in claims if c.status == "approved"}
    expired_items = set()
    if approved_items:
        expired_items = set(
            await session.scalars(
                select(FoundItem.id).where(
                    FoundItem.id.in_(approved_items), FoundItem.status == "expired"
                )
            )
        )
    return [
        _out(c, pickup_revoked=c.status == "approved" and c.found_item_id in expired_items)
        for c in claims
    ]


@router.get("/api/claims", response_model=list[ClaimOut])
async def list_mine(user: CurrentUser, session: SessionDep):
    return await _owner_claims_out(session, await service.list_mine(session, user.id))


@router.get("/api/claims/{claim_id}", response_model=ClaimOut)
async def get_one(claim_id: int, user: CurrentUser, session: SessionDep):
    claim = await service.get_own(session, claim_id, user.id)
    [response] = await _owner_claims_out(session, [claim])
    return response


@router.post("/api/claims/{claim_id}/pickup-code", response_model=PickupCodeOut)
async def pickup_code(claim_id: int, user: CurrentUser, session: SessionDep):
    issued = await service.new_pickup_code(session, claim_id, user.id)
    return PickupCodeOut(
        compartment=issued.compartment, pickup_code=issued.code, expires_at=issued.expires_at
    )


# ---------- admin ----------


async def _admin_out(session, claim: Claim) -> AdminClaimOut:
    item = await items.get_item(session, claim.found_item_id)
    report = await session.get(LostReport, claim.lost_report_id)
    return AdminClaimOut(
        id=claim.id,
        user_id=claim.user_id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=claim.status,
        verification_state=claim.verification_state,
        next_action=claim.next_action,
        ownership_score=claim.ownership_score,
        critical_conflict=claim.critical_conflict,
        created_at=claim.created_at,
        decision_note=claim.decision_note,
        owner_description=report.description if report else None,
        owner_identifying_details=report.unique_marks if report else None,
        evidence=[EvidenceOut.model_validate(e) for e in claim.evidence],
        item_summary=item.public_summary,
        item_private_attributes=[AttributeIO.model_validate(a) for a in item.private_attributes()],
    )


@router.get("/api/admin/claims", response_model=list[AdminClaimOut], tags=["admin"])
async def admin_list(
    _: AdminUser,
    session: SessionDep,
    status: str | None = "in_review",
    found_item_id: int | None = None,
):
    return [
        await _admin_out(session, claim)
        for claim in await service.list_by_status(session, status, found_item_id)
    ]


@router.get("/api/admin/claims/{claim_id}", response_model=AdminClaimOut, tags=["admin"])
async def admin_get(claim_id: int, _: AdminUser, session: SessionDep):
    return await _admin_out(session, await service.get(session, claim_id))


@router.post("/api/admin/claims/{claim_id}/decision", response_model=ClaimOut, tags=["admin"])
async def admin_decide(claim_id: int, body: DecisionIn, admin: AdminUser, session: SessionDep):
    return _out(
        await service.decide(session, claim_id, admin.id, body.decision, body.note, body.proof)
    )
