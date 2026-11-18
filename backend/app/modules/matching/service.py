import logging
import re
from collections import Counter
from datetime import timedelta
from typing import get_args

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.core.db import utcnow
from app.modules.found_items import service as items
from app.modules.found_items.models import FoundItem
from app.modules.lost_reports import service as reports
from app.modules.lost_reports.models import LostReport
from app.modules.matching import policy
from app.modules.matching.models import MatchCandidate
from app.modules.matching.schemas import CandidateOut
from app.shared import audit
from app.shared.ai.provider import AIError, get_ai_provider
from app.shared.ai.readiness import mark_ai_unavailable
from app.shared.vocab import Category, Color

log = logging.getLogger(__name__)
SEARCH_TOLERANCE = timedelta(days=policy.RETRIEVAL_TOLERANCE_DAYS)
SEMANTIC_BATCH = 24
PAGE_SIZE = 5


def _lost_text(report: LostReport) -> str:
    return " ".join(
        part
        for part in (
            report.color,
            report.brand,
            report.model,
            report.material,
            report.description,
            report.unique_marks,
        )
        if part
    )


def _found_text(item: FoundItem) -> str:
    description = (item.description or item.note or "")[:1000]
    if item.observed_model():
        return description
    estimates = [*item.model_candidates(), *item.model_candidates(less_likely=True)]
    if model := item.attr("model"):
        estimates.append(model)
    for estimate in sorted(set(estimates), key=len, reverse=True):
        description = re.sub(
            rf"(?<!\w){re.escape(estimate)}(?!\w)",
            "device of uncertain model",
            description,
            flags=re.IGNORECASE,
        )
    return description


def _found_facts(item: FoundItem) -> policy.FoundFacts:
    reliability = {
        attr.name: attr.confidence for attr in item.attributes if attr.confidence is not None
    }
    confirmed_model = item.observed_model()
    possible_models = item.model_candidates()
    less_likely = item.model_candidates(less_likely=True)
    legacy_guess = item.attr("model")
    if legacy_guess and not confirmed_model and not (possible_models or less_likely):
        possible_models = (legacy_guess,)
    reliability.pop("model", None)
    return policy.FoundFacts(
        item.category,
        item.location,
        item.found_at,
        item.attr("color"),
        item.attr("brand"),
        confirmed_model,
        item.attr("material"),
        reliability,
        model_candidates=possible_models,
        less_likely_models=less_likely,
    )


def _pool_snapshot(pool: list[FoundItem]) -> list[tuple]:
    return [
        (
            item.id,
            item.ai_status,
            item.category,
            item.description,
            item.note,
            tuple(sorted((a.id, a.value, a.confidence) for a in item.attributes)),
        )
        for item in pool
    ]


async def candidates(
    session: AsyncSession, report_id: int, owner_id: int, offset: int = 0
) -> list[CandidateOut]:
    report = await reports.get_own(session, report_id, owner_id)
    if report.status != "open":
        return []
    lost = policy.LostFacts(
        report.category,
        report.location,
        report.lost_at,
        report.color,
        report.brand,
        report.model,
        report.material,
    )

    found_after = report.lost_at - SEARCH_TOLERANCE if report.lost_at else None
    pool = await items.stored_items(session, found_after)
    snapshot = _pool_snapshot(pool)
    await session.commit()
    provider = get_ai_provider()
    query = _lost_text(report)
    semantic: list[float | None] = []
    for start in range(0, len(pool), SEMANTIC_BATCH):
        batch = pool[start : start + SEMANTIC_BATCH]
        try:
            values = await provider.compare_texts(query, [_found_text(item) for item in batch])
            if len(values) != len(batch):
                raise AIError("Incomplete similarity scores")
            semantic.extend(
                value if item.description or item.note else None
                for item, value in zip(batch, values, strict=True)
            )
        except AIError:
            mark_ai_unavailable()
            log.warning(
                "Semantic ranking unavailable for report %s; using observed fields", report.id
            )
            semantic.extend([None] * len(batch))

    colors = Counter(item.attr("color") for item in pool if item.attr("color"))
    color_count = sum(colors.values())
    scored = []
    shown = set()
    for item, sem in zip(pool, semantic, strict=True):
        found = _found_facts(item)
        frequency = colors[found.color] / color_count if color_count >= 5 else None
        scored.append((item.id, policy.score(lost, found, sem, frequency)))
        if policy.plausible(lost, found, sem):
            shown.add(item.id)
    ranked = sorted(
        ((item_id, points) for item_id, points in scored if item_id in shown),
        key=lambda entry: (-entry[1]["total"], entry[0]),
    )

    locked_report = await session.scalar(
        select(LostReport)
        .where(LostReport.id == report_id, LostReport.status == "open")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_report is None:
        return []
    latest = await items.stored_items(session, found_after)
    if _pool_snapshot(latest) != snapshot:
        # An item arrived or left during the model call. Keep the newer ranking.
        return await cached_candidates(session, report_id, owner_id, offset, refresh_unranked=False)

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
    locked_report.ranked_at = utcnow()
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
    return [_candidate_out(by_id[item_id]) for item_id, _ in ranked[offset : offset + PAGE_SIZE]]


def _candidate_out(item: FoundItem) -> CandidateOut:
    category = item.category if item.category in get_args(Category) else "other"
    color = next(
        (
            a.value
            for a in item.attributes
            if a.name in {"color", "colour"}
            and a.visibility == "public"
            and a.value in get_args(Color)
        ),
        None,
    )
    return CandidateOut(
        found_item_id=item.id,
        category=category,
        color=color,
        location=item.location if item.location in get_settings().locations else "other",
        found_date=item.found_at.date(),
    )


async def cached_candidates(
    session: AsyncSession,
    report_id: int,
    owner_id: int,
    offset: int = 0,
    *,
    refresh_unranked: bool = True,
) -> list[CandidateOut]:
    report = await reports.get_own(session, report_id, owner_id)
    if report.status != "open":
        return []
    if refresh_unranked and report.ranked_at is None:
        return await candidates(session, report_id, owner_id, offset)
    rows = await session.scalars(
        select(FoundItem)
        .join(MatchCandidate, FoundItem.id == MatchCandidate.found_item_id)
        .where(
            MatchCandidate.lost_report_id == report_id,
            MatchCandidate.shown.is_(True),
            FoundItem.status == "open",
            _visible_category(report.category),
        )
        .order_by(MatchCandidate.total.desc(), FoundItem.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    return [_candidate_out(item) for item in rows]


async def refresh_for_report(report_id: int, owner_id: int) -> None:
    try:
        async with db.SessionLocal() as session:
            await candidates(session, report_id, owner_id)
    except Exception:
        log.exception("Could not update matches for report %s", report_id)


async def refresh_for_item(item_id: int) -> None:
    async with db.SessionLocal() as session:
        item = await session.get(FoundItem, item_id)
        if item is None or item.status != "open":
            return
        reports_to_refresh = (
            await session.execute(
                select(LostReport.id, LostReport.owner_id).where(
                    LostReport.status == "open",
                    or_(
                        LostReport.lost_at.is_(None),
                        LostReport.lost_at <= item.found_at + SEARCH_TOLERANCE,
                    ),
                )
            )
        ).all()
    for report_id, owner_id in reports_to_refresh:
        await refresh_for_report(report_id, owner_id)


def _visible_category(report_category: str):
    # Reapply eligibility to rankings saved before the category rule changed.
    category = func.replace(func.lower(func.trim(FoundItem.category)), "_", " ")
    return or_(
        category.is_(None),
        category.not_in(
            name.replace("_", " ") for name in policy.incompatible_categories(report_category)
        ),
        MatchCandidate.semantic >= policy.CROSS_CATEGORY_SIMILARITY * 100,
    )


async def shown_match(
    session: AsyncSession, report: LostReport, item_id: int
) -> MatchCandidate | None:
    """Return the candidate that the owner was shown, including its stored score."""
    return await session.scalar(
        select(MatchCandidate)
        .join(FoundItem, FoundItem.id == MatchCandidate.found_item_id)
        .where(
            MatchCandidate.lost_report_id == report.id,
            MatchCandidate.found_item_id == item_id,
            MatchCandidate.shown.is_(True),
            _visible_category(report.category),
        )
    )
