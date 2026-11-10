from fastapi import APIRouter

from app.modules.claims import service
from app.modules.claims.models import Claim
from app.modules.claims.policy import MESSAGES
from app.modules.claims.schemas import (
    AdminClaimOut,
    ClaimIn,
    ClaimOut,
    DecisionIn,
    EvidenceOut,
    PickupCodeOut,
)
from app.modules.found_items import service as items
from app.modules.found_items.schemas import AttributeIO
from app.modules.identity.deps import AdminUser, CurrentUser, SessionDep

router = APIRouter(tags=["claims"])


def _out(claim: Claim, issued=None) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=claim.status,
        message=MESSAGES[claim.status],
        created_at=claim.created_at,
        compartment=issued.compartment if issued else None,
        pickup_code=issued.code if issued else None,
        pickup_expires_at=issued.expires_at if issued else None,
    )


@router.post("/api/claims", response_model=ClaimOut, status_code=201)
async def submit(body: ClaimIn, user: CurrentUser, session: SessionDep):
    claim, issued = await service.submit(
        session,
        user.id,
        body.lost_report_id,
        body.found_item_id,
        [e.model_dump() for e in body.evidence],
    )
    return _out(claim, issued)


@router.get("/api/claims", response_model=list[ClaimOut])
async def list_mine(user: CurrentUser, session: SessionDep):
    return [_out(c) for c in await service.list_mine(session, user.id)]


@router.get("/api/claims/{claim_id}", response_model=ClaimOut)
async def get_one(claim_id: int, user: CurrentUser, session: SessionDep):
    return _out(await service.get_own(session, claim_id, user.id))


@router.post("/api/claims/{claim_id}/pickup-code", response_model=PickupCodeOut)
async def pickup_code(claim_id: int, user: CurrentUser, session: SessionDep):
    issued = await service.new_pickup_code(session, claim_id, user.id)
    return PickupCodeOut(
        compartment=issued.compartment, pickup_code=issued.code, expires_at=issued.expires_at
    )


# ---------- admin ----------


async def _admin_out(session, claim: Claim) -> AdminClaimOut:
    item = await items.get_item(session, claim.found_item_id)
    return AdminClaimOut(
        id=claim.id,
        user_id=claim.user_id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=claim.status,
        ownership_score=claim.ownership_score,
        critical_conflict=claim.critical_conflict,
        created_at=claim.created_at,
        decision_note=claim.decision_note,
        evidence=[EvidenceOut.model_validate(e) for e in claim.evidence],
        item_summary=item.public_summary,
        item_private_attributes=[AttributeIO.model_validate(a) for a in item.private_attributes()],
    )


@router.get("/api/admin/claims", response_model=list[AdminClaimOut], tags=["admin"])
async def admin_list(_: AdminUser, session: SessionDep, status: str | None = "in_review"):
    return [await _admin_out(session, c) for c in await service.list_by_status(session, status)]


@router.get("/api/admin/claims/{claim_id}", response_model=AdminClaimOut, tags=["admin"])
async def admin_get(claim_id: int, _: AdminUser, session: SessionDep):
    return await _admin_out(session, await service.get(session, claim_id))


@router.post("/api/admin/claims/{claim_id}/decision", response_model=ClaimOut, tags=["admin"])
async def admin_decide(claim_id: int, body: DecisionIn, admin: AdminUser, session: SessionDep):
    return _out(await service.decide(session, claim_id, admin.id, body.decision, body.note))
