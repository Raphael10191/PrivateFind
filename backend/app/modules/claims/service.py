import logging
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, not_found
from app.modules.claims import policy
from app.modules.claims.models import Claim, OwnershipEvidence
from app.modules.found_items import service as items
from app.modules.identity.models import User
from app.modules.locker import service as locker_service
from app.modules.lost_reports import service as reports
from app.modules.lost_reports.models import LostReport
from app.modules.matching import service as matching
from app.modules.matching.models import MatchCandidate
from app.shared import audit, storage
from app.shared.ai.provider import (
    AIError,
    Photo,
    PhotoFinding,
    get_ai_provider,
)
from app.shared.vocab import CRITICAL_TYPES

log = logging.getLogger("uvicorn.error")
SERIAL_IN_DESCRIPTION = re.compile(
    r"\b(?:serial(?:\s+(?:number|no\.?))?|seriennummer|s/n)\s*"
    r"(?:(?:ends? (?:in|with)|ending (?:in|with)|endet auf|is|ist)\s*)?"
    r"[:#=]?\s*([a-z0-9][a-z0-9-]{3,39})\b",
    re.IGNORECASE,
)
UNCERTAIN_DETAIL = re.compile(
    r"\b(?:maybe|perhaps|possibly|probably|not sure|either|or|vielleicht|eventuell|"
    r"wahrscheinlich|nicht sicher|oder)\b",
    re.IGNORECASE,
)

# ---------- owner ----------


async def submit(
    session: AsyncSession,
    user_id: int,
    report_id: int,
    item_id: int,
    evidence: list[dict],
    *,
    description: str | None = None,
) -> tuple[Claim, locker_service.IssuedCode | None]:
    report = await reports.get_own(session, report_id, user_id)
    if report.status != "open":
        raise AppError(409, "report_closed", "This report is no longer open.")
    item = await items.get_item(session, item_id)
    match = await matching.shown_match(session, report, item.id)
    if match is None:
        raise AppError(409, "not_a_candidate", "This item is not a candidate for your report.")
    if item.status != "open":
        raise AppError(409, "item_unavailable", "This item is no longer available.")
    await _check_attempts(session, user_id, item_id, lock=False)
    initial = "\n".join(filter(None, (report.description, report.unique_marks)))
    supplied = "\n".join(filter(None, (description, *(entry["value"] for entry in evidence))))
    previous = await _open_claim(session, user_id, match.id)
    revision = (previous.id, previous.attempt_no) if previous else None
    earlier: dict[int, list[str]] = {}
    if previous:
        for entry in previous.evidence:
            if entry.type == "submission":
                earlier.setdefault(entry.attempt_no or 1, []).append(entry.value)
    supplementary = "\n".join(filter(None, [*map("".join, earlier.values()), supplied]))
    visual = getattr(get_ai_provider(), "verify_photos", None)
    original: list[PhotoFinding] = []
    additional: list[PhotoFinding] = []
    photo_failure = False
    await session.commit()
    if callable(visual) and item.photos:
        try:
            photos = [
                Photo(storage.read_photo(p.file_name))
                for p in sorted(item.photos, key=lambda photo: photo.id)[
                    : get_settings().max_photos
                ]
            ]
            for text, findings in ((initial, original), (supplementary, additional)):
                if text:
                    findings.extend(
                        _grounded_findings(
                            text,
                            await visual(photos, text),
                            len(photos),
                            model_observed=item.observed_model() is not None,
                        )
                    )
        except (AIError, OSError, ValueError):
            log.warning("[VERIFY] Photo check unavailable for item %s", item.id)
            original.clear()
            additional.clear()
            photo_failure = True

    # Serialize pickup decisions and attempts before trusting an earlier snapshot.
    await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
    await locker_service.compartment_for_item(session, item.id, lock=True)
    await session.refresh(item, ["status"], with_for_update=True)
    if item.status != "open":
        raise AppError(409, "item_unavailable", "This item is no longer available.")
    if (await _lock_report(session, report_id)).status != "open":
        raise AppError(409, "report_closed", "This report is no longer open.")
    await _check_attempts(session, user_id, item_id)
    claim = await _open_claim(session, user_id, match.id, lock=True)
    latest_revision = (claim.id, claim.attempt_no) if claim else None
    if latest_revision != revision:
        raise AppError(409, "claim_updated", "Your claim changed. Refresh before checking again.")
    competing = await session.scalar(
        select(Claim.id)
        .where(
            Claim.found_item_id == item_id, Claim.user_id != user_id, Claim.status == "in_review"
        )
        .limit(1)
        .with_for_update()
    )
    trusted_id = next(
        (
            policy.normalized_identifier(a.value)
            for a in item.private_attributes()
            if a.name in CRITICAL_TYPES
            and a.source == "admin"
            and len(policy.normalized_identifier(a.value)) >= 8
        ),
        None,
    )
    identifiers = [
        policy.normalized_identifier(e["value"]) for e in evidence if e["type"] in CRITICAL_TYPES
    ]
    identifiers.extend(
        policy.normalized_identifier(match.group(1))
        for line in (initial + "\n" + supplementary).splitlines()
        if not UNCERTAIN_DETAIL.search(line)
        for match in SERIAL_IN_DESCRIPTION.finditer(line)
        if any(char.isdigit() for char in match.group(1))
    )
    verdict = policy.assess(
        original,
        additional,
        category=item.category,
        trusted_identifier=trusted_id,
        identifiers=tuple(
            value for value in identifiers if trusted_id and len(value) == len(trusted_id)
        ),
        competing=competing is not None,
        exposed=item.owner_details_exposed,
    )
    if photo_failure and verdict.state != "refuted":
        verdict = policy.Verdict("unresolved", "retry_photo_check")

    new_claim = claim is None
    if new_claim:
        claim = Claim(user_id=user_id, match_candidate=match, attempt_no=1)
        session.add(claim)
    else:
        claim.attempt_no += 1
    claim.status = verdict.status
    claim.verification_state = verdict.state
    claim.next_action = verdict.action
    claim.ownership_score = None
    claim.critical_conflict = verdict.state == "refuted"
    claim.decided_at = utcnow() if verdict.status != "in_review" else None
    for source, text in (
        ("initial_report", initial if new_claim else ""),
        ("submission", supplied),
    ):
        claim.evidence.extend(
            OwnershipEvidence(
                type=source, value=text[start : start + 250], attempt_no=claim.attempt_no
            )
            for start in range(0, len(text), 250)
        )
    claim.evidence.extend(
        OwnershipEvidence(
            attempt_no=claim.attempt_no,
            type=finding.kind,
            value=finding.quote,
            result={"confirmed": "match", "contradicted": "mismatch"}.get(
                finding.status, "not_verifiable"
            ),
        )
        for finding in original + additional
    )
    await session.flush()
    issued = await _approve(session, claim) if verdict.status == "approved" else None
    audit.log(
        session,
        "claim_submitted",
        "claim",
        claim.id,
        actor_type="user",
        actor_id=user_id,
        decision=verdict.state,
        observations=[
            {
                "part": f.part,
                "photo": f.photo_index,
                "status": f.status,
                "kind": f.kind,
                "distinctive": f.distinctive,
                "strong": f.strong,
                "source": source,
            }
            for source, findings in (("initial", original), ("additional", additional))
            for f in findings
        ],
    )
    await session.commit()
    log.info("[VERIFY] Claim %s -> %s", claim.id, verdict.state)
    return claim, issued


async def _open_claim(
    session: AsyncSession, user_id: int, match_id: int, *, lock: bool = False
) -> Claim | None:
    query = (
        select(Claim)
        .where(Claim.user_id == user_id, Claim.match_id == match_id, Claim.status == "in_review")
        .order_by(Claim.id.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


def _grounded_findings(
    text: str, findings: list[PhotoFinding], photo_count: int, *, model_observed: bool = False
) -> list[PhotoFinding]:
    normalized = " ".join(text.casefold().split())
    uncertain_segments = [
        " ".join(segment.casefold().split())
        for segment in re.split(r"[.!?;\n]", text)
        if UNCERTAIN_DETAIL.search(segment)
    ]
    seen: set[tuple[str, str]] = set()
    grounded = []
    for finding in findings:
        quote = " ".join(finding.quote.casefold().split())
        quoted = re.compile(rf"(?<!\w){re.escape(quote)}(?!\w)")
        if not quote or not quoted.search(normalized):
            raise AIError("The photo result references text outside the claim")
        if finding.status in {"confirmed", "contradicted"} and (
            finding.photo_index is None or not 0 <= finding.photo_index < photo_count
        ):
            raise AIError("The photo result references an invalid photo")
        if UNCERTAIN_DETAIL.search(quote) or any(quoted.search(s) for s in uncertain_segments):
            finding = finding.model_copy(update={"status": "ambiguous", "photo_index": None})
        if finding.kind == "model" and not model_observed:
            finding = finding.model_copy(
                update={
                    "status": "unobservable",
                    "photo_index": None,
                    "observation": None,
                }
            )
        key = (quote, finding.status)
        if key not in seen:
            grounded.append(finding)
            seen.add(key)
    return grounded


async def _check_attempts(
    session: AsyncSession, user_id: int, item_id: int, *, lock: bool = True
) -> None:
    settings = get_settings()
    since = utcnow() - timedelta(hours=settings.claim_cooldown_h)
    attempts = (
        select(Claim.found_item_id)
        .select_from(audit.AuditLog)
        .join(Claim, audit.AuditLog.entity_id == Claim.id)
        .where(
            audit.AuditLog.action == "claim_submitted",
            audit.AuditLog.entity_type == "claim",
            audit.AuditLog.at >= since,
            Claim.user_id == user_id,
            audit.AuditLog.actor_id == user_id,
        )
    )
    # A locking read sees current attempts even when a MySQL transaction has an older snapshot.
    recent_items = list(await session.scalars(attempts.with_for_update() if lock else attempts))
    if recent_items.count(item_id) >= settings.max_failed_claims or len(recent_items) >= 12:
        raise AppError(429, "claim_cooldown", "Too many attempts. Please try again later.")


async def _lock_report(session: AsyncSession, report_id: int) -> LostReport:
    return await session.scalar(
        select(LostReport)
        .where(LostReport.id == report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _lock_report_for_release(session: AsyncSession, claim: Claim) -> LostReport:
    report = await _lock_report(session, claim.lost_report_id)
    other = await session.scalar(
        select(Claim.id)
        .join(MatchCandidate, MatchCandidate.id == Claim.match_id)
        .where(
            MatchCandidate.lost_report_id == report.id,
            Claim.id != claim.id,
            Claim.status == "approved",
        )
        .limit(1)
        .with_for_update()
    )
    if report.status != "open" or other is not None:
        raise AppError(
            409, "report_already_resolved", "This report already has an authorized return."
        )
    return report


async def _approve(session: AsyncSession, claim: Claim) -> locker_service.IssuedCode:
    """Reserve the item (first approval wins), close competing claims, issue the pickup code."""
    await locker_service.compartment_for_item(session, claim.found_item_id, lock=True)
    await _lock_report_for_release(session, claim)
    if not await items.try_reserve(session, claim.found_item_id):
        await session.rollback()
        raise AppError(409, "item_unavailable", "This item is no longer available.")
    claim.status = "approved"
    claim.decided_at = utcnow()
    competing = await session.scalars(
        select(Claim)
        .where(
            Claim.found_item_id == claim.found_item_id,
            Claim.id != claim.id,
            Claim.status == "in_review",
        )
        .with_for_update()
    )
    for other in competing:
        other.status = "rejected"
        other.verification_state = "unresolved"
        other.next_action = None
        other.decision_note = "This item is no longer available."
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


async def list_by_status(
    session: AsyncSession, status: str | None, found_item_id: int | None = None
) -> list[Claim]:
    q = select(Claim).order_by(Claim.id.desc())
    if status:
        q = q.where(Claim.status == status)
    if found_item_id is not None:
        q = q.where(Claim.found_item_id == found_item_id)
    return list(await session.scalars(q))


async def get(session: AsyncSession, claim_id: int) -> Claim:
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise not_found("Claim")
    return claim


async def decide(
    session: AsyncSession,
    claim_id: int,
    admin_id: int,
    decision: str,
    note: str | None,
    proof: str | None,
) -> Claim:
    claim = await get(session, claim_id)
    item = await items.get_item(session, claim.found_item_id)
    compartment = await locker_service.compartment_for_item(session, item.id, lock=True)
    await _lock_report(session, claim.lost_report_id)
    await session.refresh(claim, with_for_update=True)
    await session.refresh(item, ["status"], with_for_update=True)
    if claim.status != "in_review":
        raise AppError(409, "not_in_review", "Only claims in review can be decided.")
    if decision != "reject":
        if not note or len(note.strip()) < 10:
            raise AppError(
                422, "review_note_required", "Document what was checked before authorizing release."
            )
        if item.status != "open":
            raise AppError(409, "item_unavailable", "This item is no longer available.")
    if decision == "approve":
        if proof not in {"dated_identifier_record", "live_device_control", "independent_record"}:
            raise AppError(
                422, "independent_proof_required", "Select the independent proof you checked."
            )
        await _approve(session, claim)
        claim.verification_state = "verified"
    elif decision == "handed_over":
        competing = await session.scalar(
            select(Claim.id)
            .where(
                Claim.found_item_id == item.id,
                Claim.user_id != claim.user_id,
                Claim.status == "in_review",
            )
            .limit(1)
            .with_for_update()
        )
        if item.category not in policy.LOW_RISK_CATEGORIES or competing is not None:
            raise AppError(409, "handover_unavailable", "This handover requires independent proof.")
        if proof != "in_person_low_risk":
            raise AppError(
                422, "handover_confirmation_required", "Confirm the documented in-person handover."
            )
        report = await _lock_report_for_release(session, claim)
        await items.mark_returned(session, item.id, actor_type="admin", actor_id=admin_id)
        report.status = "resolved"
        await locker_service.clear_item_access(session, item.id, compartment)
        # Keep the legacy enum while distinguishing completed handovers from code authorizations.
        claim.status = "approved"
        claim.verification_state = "handed_over"
    else:
        claim.status = "rejected"
        claim.verification_state = "refuted"
    claim.next_action = None
    claim.decided_at = utcnow()
    claim.decided_by = admin_id
    claim.decision_note = note
    audit.log(
        session,
        "claim_decided",
        "claim",
        claim.id,
        actor_type="admin",
        actor_id=admin_id,
        decision=claim.verification_state,
        proof=proof,
        note=note,
    )
    await session.commit()
    return claim
