import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.modules.found_items import service as items
from app.modules.found_items.models import FoundItem
from app.modules.lost_reports import service as reports
from app.modules.lost_reports.models import LostReport
from app.modules.matching import policy
from app.modules.matching.models import MatchCandidate
from app.modules.matching.schemas import Breakdown, CandidateOut
from app.shared import audit
from app.shared.ai.provider import get_ai_provider

log = logging.getLogger(__name__)


def _lost_text(r) -> str:
    return " ".join(p for p in [r.color, r.brand, r.model, r.description] if p)


async def candidates(session: AsyncSession, report_id: int, owner_id: int) -> list[CandidateOut]:
    report = await reports.get_own(session, report_id, owner_id)
    if report.status != "open":
        return []
    settings = get_settings()
    lost = policy.LostFacts(
        report.category, report.location, report.lost_at, report.color, report.brand, report.model
    )

    pool = await items.stored_items(session, report.category, report.lost_at - timedelta(days=1))
    await session.commit()
    semantic = (
        await get_ai_provider().compare_texts(
            _lost_text(report), [i.description or i.note or "" for i in pool]
        )
        if pool
        else []
    )

    scored = []
    for item, sem in zip(pool, semantic, strict=True):
        found = policy.FoundFacts(
            item.category,
            item.location,
            item.found_at,
            item.attr("color"),
            item.attr("brand"),
            item.attr("model"),
        )
        scored.append((item.id, policy.score(lost, found, sem)))
    top = policy.top_candidates(scored, settings.match_threshold, settings.max_candidates)
    shown = {item_id for item_id, _ in top}

    locked_report = await session.scalar(
        select(LostReport.id)
        .where(LostReport.id == report_id, LostReport.status == "open")
        .with_for_update()
    )
    if locked_report is None:
        return []
    latest = await items.stored_items(session, report.category, report.lost_at - timedelta(days=1))
    if {item.id for item in latest} != {item.id for item in pool}:
        # An item arrived or left during the model call. Keep the newer ranking.
        return await cached_candidates(session, report_id, owner_id)

    # Claims reference match_id: update rows in place, never delete their history.
    existing = {
        c.found_item_id: c
        for c in await session.scalars(
            select(MatchCandidate)
            .where(MatchCandidate.lost_report_id == report.id)
            .with_for_update()
        )
    }
    for candidate in existing.values():
        candidate.shown = False
    for item_id, points in scored:
        candidate = existing.get(item_id)
        if candidate is None:
            candidate = MatchCandidate(lost_report_id=report.id, found_item_id=item_id)
            session.add(candidate)
        candidate.shown = item_id in shown
        for name, value in points.items():
            # Simon stores partial scores on a 0..100 scale, before weighting.
            setattr(
                candidate, name, value if name == "total" else value / policy.WEIGHTS[name] * 100
            )
    audit.log(
        session,
        "candidates_ranked",
        "lost_report",
        report.id,
        actor_type="user",
        actor_id=owner_id,
        scored=len(scored),
        shown=sorted(shown),
    )
    await session.commit()

    by_id = {i.id: i for i in pool}
    return [_candidate_out(by_id[item_id], points) for item_id, points in top]


def _candidate_out(item: FoundItem, points: dict) -> CandidateOut:
    return CandidateOut(
        found_item_id=item.id,
        score=points["total"],
        breakdown=Breakdown(**{k: v for k, v in points.items() if k != "total"}),
        category=item.category,
        color=item.attr("color"),
        location=item.location,
        found_date=item.found_at.date(),
        public_summary=item.public_summary,
    )


async def cached_candidates(
    session: AsyncSession, report_id: int, owner_id: int
) -> list[CandidateOut]:
    report = await reports.get_own(session, report_id, owner_id)
    if report.status != "open":
        return []
    rows = await session.execute(
        select(MatchCandidate, FoundItem)
        .join(FoundItem, FoundItem.id == MatchCandidate.found_item_id)
        .where(
            MatchCandidate.lost_report_id == report_id,
            MatchCandidate.shown.is_(True),
            FoundItem.status == "open",
        )
        .order_by(MatchCandidate.total.desc(), FoundItem.id)
    )
    return [
        _candidate_out(
            item,
            {
                "total": match.total,
                **{
                    key: round(getattr(match, key) * weight / 100, 1)
                    for key, weight in policy.WEIGHTS.items()
                },
            },
        )
        for match, item in rows
    ]


async def refresh_for_report(report_id: int, owner_id: int) -> None:
    try:
        async with db.SessionLocal() as session:
            await candidates(session, report_id, owner_id)
    except Exception:
        log.exception("Could not update matches for report %s", report_id)


async def refresh_for_item(item_id: int) -> None:
    async with db.SessionLocal() as session:
        item = await session.get(FoundItem, item_id)
        if item is None or item.status != "open" or item.ai_status != "done":
            return
        category = LostReport.category == "other"
        if item.category == "other":
            category = LostReport.category.is_not(None)
        elif item.category is not None:
            category = LostReport.category.in_([item.category, "other"])
        reports_to_refresh = (
            await session.execute(
                select(LostReport.id, LostReport.owner_id).where(
                    LostReport.status == "open",
                    category,
                    LostReport.lost_at <= item.found_at + timedelta(days=1),
                )
            )
        ).all()
    for report_id, owner_id in reports_to_refresh:
        await refresh_for_report(report_id, owner_id)


async def shown_match(session: AsyncSession, report_id: int, item_id: int) -> MatchCandidate | None:
    """Return the candidate that the owner was shown, including its stored score."""
    return await session.scalar(
        select(MatchCandidate).where(
            MatchCandidate.lost_report_id == report_id,
            MatchCandidate.found_item_id == item_id,
            MatchCandidate.shown.is_(True),
        )
    )
