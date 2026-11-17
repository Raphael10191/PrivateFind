"""Rank candidates by category, location, time, attributes and description similarity."""

import re
from dataclasses import dataclass
from datetime import datetime

WEIGHTS = {"category": 15, "location": 10, "time": 10, "attributes": 25, "semantic": 40}
BRAND_ALIASES = {
    "iphone": "apple",
    "ipad": "apple",
    "macbook": "apple",
    "airpods": "apple",
    "imac": "apple",
    "apple watch": "apple",
    "galaxy": "samsung",
    "pixel": "google",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "xperia": "sony",
    "thinkpad": "lenovo",
    "surface": "microsoft",
    "jordan": "nike",
    "beats": "apple",
}
COLOR_GROUPS = (
    {"black", "gray"},
    {"gray", "silver"},
    {"blue", "black"},
    {"gold", "yellow", "beige"},
    {"beige", "brown"},
    {"red", "pink"},
    {"pink", "purple"},
    {"blue", "purple"},
    {"white", "silver"},
)


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
    if lost.category == found.category:
        return 1.0
    return 0.4 if "other" in (lost.category, found.category) else 0.0


def location_score(lost: LostFacts, found: FoundFacts) -> float:
    if lost.location == found.location:
        return 1.0
    return 0.5 if "other" in (lost.location, found.location) else 0.15


def time_score(lost: LostFacts, found: FoundFacts) -> float:
    hours = (found.found_at - lost.lost_at).total_seconds() / 3600
    if hours < -24:  # found well before it was lost: almost certainly another item
        return 0.0
    for limit, score in ((24, 1.0), (72, 0.6), (168, 0.3)):
        if hours <= limit:
            return score
    return 0.1


def _tokens(value: str | None) -> set[str]:
    return set(re.findall(r"[^\W_]+", (value or "").casefold()))


def norm_brand(brand: str | None, model: str | None = None) -> str | None:
    words = re.findall(r"[^\W_]+", (brand or "").casefold())
    explicit = " ".join(word for word in words if word not in {"the", "inc", "co"})
    text = explicit or " ".join(re.findall(r"[^\W_]+", (model or "").casefold()))
    for alias, manufacturer in BRAND_ALIASES.items():
        if re.search(rf"\b{alias}\b", text):
            return manufacturer
    return explicit or None


def same_brand(left: str, right: str) -> bool:
    left_words, right_words = ((norm_brand(brand) or "").split() for brand in (left, right))
    a, b = set(left_words), set(right_words)
    return bool(a and b and (a <= b or b <= a or "".join(left_words) == "".join(right_words)))


def _brand_similarity(lost: LostFacts, found: FoundFacts) -> float | None:
    left, right = norm_brand(lost.brand, lost.model), norm_brand(found.brand, found.model)
    if not left or not right:
        return None
    return float(same_brand(left, right))


def _different_model_numbers(left: str | None, right: str | None) -> bool:
    a, b = (set(re.findall(r"\d+", model or "")) for model in (left, right))
    return bool(a and b and not (a <= b or b <= a))


def model_similarity(left: str | None, right: str | None) -> float | None:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return None
    if _different_model_numbers(left, right):
        return 0.2
    if a == b:
        return 1.0
    if a <= b or b <= a:
        return 0.85
    return len(a & b) / len(a | b)


def color_similarity(left: str | None, right: str | None) -> float | None:
    a, b = ((color or "").strip().casefold().replace("grey", "gray") for color in (left, right))
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if "multicolor" in (a, b):
        return 0.5
    return 0.6 if any(a in group and b in group for group in COLOR_GROUPS) else 0.0


def attribute_score(lost: LostFacts, found: FoundFacts) -> float:
    """Average the similarities for attributes known on both sides."""
    similarities = (
        color_similarity(lost.color, found.color),
        _brand_similarity(lost, found),
        model_similarity(lost.model, found.model),
    )
    comparable = [value for value in similarities if value is not None]
    return sum(comparable) / len(comparable) if comparable else 0.5


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
    total = sum(points.values())
    if _brand_similarity(lost, found) == 0.0:
        total = min(total, 45)
    if _different_model_numbers(lost.model, found.model):
        total -= 10
    if color_similarity(lost.color, found.color) == 0.0:
        total = min(total - 15, 55)
    points["total"] = max(0, round(total))
    return points


def top_candidates(
    scored: list[tuple[int, dict]], threshold: int, limit: int
) -> list[tuple[int, dict]]:
    """Keep (item_id, points) above the threshold, best first, at most `limit`."""
    above = [s for s in scored if s[1]["total"] >= threshold]
    return sorted(above, key=lambda s: s[1]["total"], reverse=True)[:limit]
