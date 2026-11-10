from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.found_items import service as items
from app.modules.lost_reports import service as reports
from app.modules.matching import policy
from app.modules.matching.models import MatchCandidate
from app.modules.matching.schemas import Breakdown, CandidateOut
from app.shared import audit
from app.shared.ai.provider import get_ai_provider


def _lost_text(r) -> str:
    return " ".join(p for p in [r.color, r.brand, r.model, r.description] if p)


async def candidates(session: AsyncSession, report_id: int, owner_id: int) -> list[CandidateOut]:
    settings = get_settings()
    report = await reports.get_own(session, report_id, owner_id)
    lost = policy.LostFacts(
        report.category, report.location, report.lost_at, report.color, report.brand, report.model
    )

    pool = await items.stored_items(session, report.category, report.lost_at - timedelta(days=1))
    semantic = (
        await get_ai_provider().compare_texts(
            _lost_text(report), [i.description or i.note for i in pool]
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

    # Claims reference match_id: update rows in place, never delete their history.
    existing = {
        c.found_item_id: c
        for c in await session.scalars(
            select(MatchCandidate).where(MatchCandidate.lost_report_id == report.id)
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
    return [
        CandidateOut(
            found_item_id=item_id,
            score=points["total"],
            breakdown=Breakdown(**{k: v for k, v in points.items() if k != "total"}),
            category=by_id[item_id].category,
            color=by_id[item_id].attr("color"),
            location=by_id[item_id].location,
            found_date=by_id[item_id].found_at.date(),
            public_summary=by_id[item_id].public_summary,
        )
        for item_id, points in top
    ]


async def was_shown(session: AsyncSession, report_id: int, item_id: int) -> bool:
    """True if the item was in this report's candidate list (claims require it)."""
    return bool(
        await session.scalar(
            select(MatchCandidate.id).where(
                MatchCandidate.lost_report_id == report_id,
                MatchCandidate.found_item_id == item_id,
                MatchCandidate.shown.is_(True),
            )
        )
    )


async def shown_match_id(session: AsyncSession, report_id: int, item_id: int) -> int | None:
    return await session.scalar(
        select(MatchCandidate.id).where(
            MatchCandidate.lost_report_id == report_id,
            MatchCandidate.found_item_id == item_id,
            MatchCandidate.shown.is_(True),
        )
    )
