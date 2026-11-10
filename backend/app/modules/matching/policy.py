"""Hybrid Match Score (pure functions, no I/O).

Match Score = 25% category + 15% location + 15% time + 25% structured attributes + 20% semantic.
The score only ranks candidates; it never proves ownership.
"""

from dataclasses import dataclass
from datetime import datetime

WEIGHTS = {"category": 25, "location": 15, "time": 15, "attributes": 25, "semantic": 20}


@dataclass
class LostFacts:
    category: str
    location: str
    lost_at: datetime
    color: str | None = None
    brand: str | None = None
    model: str | None = None


@dataclass
class FoundFacts:
    category: str | None
    location: str
    found_at: datetime
    color: str | None = None
    brand: str | None = None
    model: str | None = None


def category_score(lost: LostFacts, found: FoundFacts) -> float:
    return 1.0 if lost.category == found.category else 0.0


def location_score(lost: LostFacts, found: FoundFacts) -> float:
    if lost.location == found.location:
        return 1.0
    return 0.5 if "other" in (lost.location, found.location) else 0.0


def time_score(lost: LostFacts, found: FoundFacts) -> float:
    hours = (found.found_at - lost.lost_at).total_seconds() / 3600
    if hours < -24:  # found well before it was lost: almost certainly another item
        return 0.0
    for limit, score in ((24, 1.0), (72, 0.6), (168, 0.3)):
        if hours <= limit:
            return score
    return 0.1


def _same(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or a in b or b in a


def attribute_score(lost: LostFacts, found: FoundFacts) -> float:
    """Share of attributes known on both sides that agree; 0.5 (neutral) if nothing to compare."""
    pairs = [(getattr(lost, f), getattr(found, f)) for f in ("color", "brand", "model")]
    comparable = [(a, b) for a, b in pairs if a and b]
    if not comparable:
        return 0.5
    return sum(_same(a, b) for a, b in comparable) / len(comparable)


def score(lost: LostFacts, found: FoundFacts, semantic: float) -> dict[str, float]:
    """Points per component (max = weight) plus 'total' (0..100, rounded)."""
    parts = {
        "category": category_score(lost, found),
        "location": location_score(lost, found),
        "time": time_score(lost, found),
        "attributes": attribute_score(lost, found),
        "semantic": max(0.0, min(1.0, semantic)),
    }
    points = {k: round(v * WEIGHTS[k], 1) for k, v in parts.items()}
    points["total"] = round(sum(points.values()))
    return points


def top_candidates(
    scored: list[tuple[int, dict]], threshold: int, limit: int
) -> list[tuple[int, dict]]:
    """Keep (item_id, points) above the threshold, best first, at most `limit`."""
    above = [s for s in scored if s[1]["total"] >= threshold]
    return sorted(above, key=lambda s: s[1]["total"], reverse=True)[:limit]
