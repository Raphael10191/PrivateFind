from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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
from app.shared.ai.readiness import require_ai_ready
from app.shared.audit import AuditLog
from app.shared.ratelimit import claim_limiter

router = APIRouter(tags=["claims"])


def _out(claim: Claim, issued=None, *, item_status: str | None = None) -> ClaimOut:
    status = claim.status
    next_action = claim.next_action
    if claim.verification_state == "handed_over":
        status = "handed_over"
    elif item_status in {"expired", "returned"}:
        if status == "approved":
            status = "collected" if item_status == "returned" else "revoked"
        elif status in {"in_review", "pending"}:
            status = "unavailable"
        next_action = None
    return ClaimOut(
        id=claim.id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=status,
        verification_state=claim.verification_state,
        next_action=next_action,
        message=NEXT_ACTION_MESSAGES.get(next_action, MESSAGES[status]),
        created_at=claim.created_at,
        compartment=issued.compartment if issued else None,
        pickup_code=issued.code if issued else None,
        pickup_expires_at=issued.expires_at if issued else None,
    )


@router.post(
    "/api/claims",
    response_model=ClaimOut,
    status_code=201,
    dependencies=[Depends(require_ai_ready)],
)
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
    if not claims:
        return []
    item_states = await session.execute(
        select(FoundItem.id, FoundItem.status).where(
            FoundItem.id.in_({claim.found_item_id for claim in claims})
        )
    )
    statuses = dict(item_states.all())
    return [_out(claim, item_status=statuses.get(claim.found_item_id)) for claim in claims]


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


async def _admin_out(session: AsyncSession, claim: Claim, details: dict | None) -> AdminClaimOut:
    item = await items.get_item(session, claim.found_item_id)
    report = await session.get(LostReport, claim.lost_report_id)
    return AdminClaimOut(
        id=claim.id,
        user_id=claim.user_id,
        found_item_id=claim.found_item_id,
        lost_report_id=claim.lost_report_id,
        status=claim.status,
        item_status=item.status,
        verification_state=claim.verification_state,
        next_action=claim.next_action,
        ownership_score=claim.ownership_score,
        critical_conflict=claim.critical_conflict,
        created_at=claim.created_at,
        decision_note=claim.decision_note,
        verification_reason=_verification_reason(claim, details),
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
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
):
    claims = await service.list_by_status(session, status, found_item_id, limit)
    details = await _latest_verification_details(session, [claim.id for claim in claims])
    return [await _admin_out(session, claim, details.get(claim.id)) for claim in claims]


@router.get("/api/admin/claims/{claim_id}", response_model=AdminClaimOut, tags=["admin"])
async def admin_get(claim_id: int, _: AdminUser, session: SessionDep):
    claim = await service.get(session, claim_id)
    details = await _latest_verification_details(session, [claim.id])
    return await _admin_out(session, claim, details.get(claim.id))


async def _latest_verification_details(
    session: AsyncSession, claim_ids: list[int]
) -> dict[int, dict]:
    if not claim_ids:
        return {}
    latest_ids = (
        select(func.max(AuditLog.id))
        .where(
            AuditLog.entity_type == "claim",
            AuditLog.entity_id.in_(claim_ids),
            AuditLog.action == "claim_submitted",
        )
        .group_by(AuditLog.entity_id)
    )
    rows = await session.execute(
        select(AuditLog.entity_id, AuditLog.details).where(AuditLog.id.in_(latest_ids))
    )
    return {claim_id: details for claim_id, details in rows if details}


def _verification_reason(claim: Claim, details: dict | None) -> str | None:
    if claim.decided_by is not None:
        return "The operator recorded this decision after a manual review."
    if claim.status == "rejected" and claim.verification_state == "unresolved":
        return claim.decision_note
    if details and details.get("decision") == claim.verification_state:
        reason = details.get("verification_reason")
        if reason:
            return reason
    if claim.status == "approved":
        confirmed = [
            entry.value
            for entry in claim.evidence
            if entry.result == "match"
            and entry.type not in {"common", "model"}
            and entry.attempt_no in (None, claim.attempt_no)
        ]
        reason = "The reason was not recorded for this earlier approval."
        if confirmed:
            details_text = "; ".join(dict.fromkeys(confirmed))
            reason += f" Recorded photo matches: {details_text}."
        return reason
    return None


@router.post("/api/admin/claims/{claim_id}/decision", response_model=ClaimOut, tags=["admin"])
async def admin_decide(claim_id: int, body: DecisionIn, admin: AdminUser, session: SessionDep):
    return _out(
        await service.decide(session, claim_id, admin.id, body.decision, body.note, body.proof)
    )
