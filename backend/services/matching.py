"""Matching Engine, Match Score v1 (work package 6.6).

Proposal 4.3: open items are filtered by category and date. The Match Score (0-100) is
    25 % category + 15 % location + 15 % time + 25 % attributes + 20 % semantic similarity
Up to three candidates with a score of at least 60 are shown. The score only ranks
candidates, it never proves ownership.

The semantic similarity (7.2) is in services/embeddings.py. As long as
SEMANTIC_ENABLED is false, the other four factors are rescaled to 0-100
(divided by 0.80), so the threshold of 60 still works.

Only PUBLIC attributes are used here. Private attributes are only for the ownership check.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import config
from backend.database.models import (
    FoundItem,
    FoundItemStatus,
    LostReport,
    MatchCandidate,
    Visibility,
)
from backend.services.embeddings import semantic_score

# Items found a little before the reported time window still count (owners guess the time)
TIME_TOLERANCE = timedelta(hours=1)
# Score for "found after the window" goes down by this much per day
TIME_DECAY_PER_DAY = 20

STOP_WORDS = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "with", "near", "floor", "room"}


@dataclass
class PartialScores:
    category: float
    location: float
    time: float
    attributes: float
    semantic: float = 0.0

    def total(self) -> float:
        w = config.MATCH_WEIGHTS
        total = (
            w["category"] * self.category
            + w["location"] * self.location
            + w["time"] * self.time
            + w["attributes"] * self.attributes
        )
        if config.SEMANTIC_ENABLED:
            total += w["semantic"] * self.semantic
        else:
            total /= 1 - w["semantic"]
        return round(min(total, 100.0), 1)


# ---------------------------------------------------------------------------
# Partial scores (each 0-100)
# ---------------------------------------------------------------------------

def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9가-힣]+", (text or "").lower()) if w not in STOP_WORDS}


def category_score(report: LostReport, item: FoundItem) -> float:
    return 100.0 if item.category and item.category == report.category else 0.0


def location_score(report_location: str, item_location: str) -> float:
    """100 same place, 60 same building, 30 some words in common, else 0.

    Locations are written like "Gwanggaeto Hall, 3rd floor": the part before the
    comma is the building.
    """
    a, b = report_location.strip().lower(), item_location.strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    building_a, building_b = a.split(",")[0].strip(), b.split(",")[0].strip()
    if building_a and building_a == building_b:
        return 60.0
    if _words(a) & _words(b):
        return 30.0
    return 0.0


def time_score(lost_from: datetime, lost_to: datetime, found_at: datetime) -> float:
    """100 if found inside the lost time window, less for every day after it."""
    if found_at < lost_from - TIME_TOLERANCE:
        return 0.0  # found before it was lost: cannot be the same item
    if found_at <= lost_to:
        return 100.0
    days_after = (found_at - lost_to).total_seconds() / 86400
    return max(0.0, round(100.0 - TIME_DECAY_PER_DAY * days_after, 1))


def attribute_score(report: LostReport, item: FoundItem) -> float:
    """Share of the item's public attributes (by weight) that the owner mentioned."""
    public = [a for a in item.attributes if a.visibility == Visibility.PUBLIC]
    if not public:
        return 0.0
    report_words = _words(" ".join(filter(None, [report.brand_model, report.description, report.unique_marks])))
    total_weight = sum(a.weight for a in public)
    matched_weight = sum(
        a.weight for a in public if _words(a.value) and _words(a.value) <= report_words
    )
    return round(100.0 * matched_weight / total_weight, 1)


def score(report: LostReport, item: FoundItem) -> PartialScores:
    return PartialScores(
        category=category_score(report, item),
        location=location_score(report.location, item.location),
        time=time_score(report.lost_from, report.lost_to, item.found_at),
        attributes=attribute_score(report, item),
        semantic=semantic_score(report, item) if config.SEMANTIC_ENABLED else 0.0,
    )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def _open_items_for(db: Session, report: LostReport) -> list[FoundItem]:
    """Filter by status, category and date (proposal 4.3)."""
    return list(
        db.scalars(
            select(FoundItem).where(
                FoundItem.status == FoundItemStatus.OPEN,
                FoundItem.category == report.category,
                FoundItem.found_at >= report.lost_from - TIME_TOLERANCE,
            )
        )
    )


def update_candidates(db: Session, report: LostReport) -> list[MatchCandidate]:
    """Calculates the score for every open item and stores all partial scores.

    Returns the top candidates (score >= 60, max. 3), best first.
    """
    existing = {c.item_id: c for c in report.match_candidates}
    results: list[MatchCandidate] = []

    for item in _open_items_for(db, report):
        parts = score(report, item)
        candidate = existing.get(item.item_id)
        if candidate is None:
            candidate = MatchCandidate(lost_report=report, found_item=item)
            db.add(candidate)
        candidate.category_score = parts.category
        candidate.location_score = parts.location
        candidate.time_score = parts.time
        candidate.attribute_score = parts.attributes
        candidate.semantic_score = parts.semantic
        candidate.total_score = parts.total()
        results.append(candidate)

    db.flush()
    top = [c for c in results if c.total_score >= config.MATCH_MIN_SCORE]
    top.sort(key=lambda c: c.total_score, reverse=True)  # best first
    return top[: config.MATCH_MAX_CANDIDATES]


def public_summary(candidate: MatchCandidate) -> dict:
    """What the owner may see: no photos, no private attributes, no finder note."""
    item = candidate.found_item
    return {
        "match_id": candidate.match_id,
        "item_id": item.item_id,
        "category": item.category,
        "found_location": item.location,
        "found_date": item.found_at.date().isoformat(),
        "public_attributes": [
            {"name": a.name, "value": a.value}
            for a in item.attributes
            if a.visibility == Visibility.PUBLIC
        ],
        "match_score": candidate.total_score,
    }
