"""Rank candidates by category, location, time, attributes and description similarity."""

import re
from dataclasses import dataclass
from datetime import datetime

from app.shared.vocab import category_key

WEIGHTS = {"category": 15, "location": 8, "time": 12, "attributes": 30, "semantic": 35}
RETRIEVAL_TOLERANCE_DAYS = 7
CATEGORY_FAMILIES = (
    {"phone", "tablet", "laptop", "headphones", "watch", "electronics"},
    {"wallet", "bag", "id_card"},
    {"clothing", "glasses", "jewelry", "watch"},
)
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
    lost_at: datetime | None
    color: str | None = None
    brand: str | None = None
    model: str | None = None
    material: str | None = None


@dataclass
class FoundFacts:
    category: str | None
    location: str
    found_at: datetime
    color: str | None = None
    brand: str | None = None
    model: str | None = None
    material: str | None = None

    reliability: dict[str, float] | None = None
    model_candidates: tuple[str, ...] = ()
    less_likely_models: tuple[str, ...] = ()


def category_score(lost: LostFacts, found: FoundFacts) -> float:
    left, right = map(category_key, (lost.category, found.category))
    if "other" in (left, right):
        return 0.5
    if left == right:
        return 1.0
    return 0.75 if any({left, right} <= group for group in CATEGORY_FAMILIES) else 0.2


def location_score(lost: LostFacts, found: FoundFacts) -> float:
    if any(value in ("", "other", None) for value in (lost.location, found.location)):
        return 0.5
    return 1.0 if lost.location == found.location else 0.3


def time_score(lost: LostFacts, found: FoundFacts) -> float:
    if lost.lost_at is None:
        return 0.5
    hours = (found.found_at - lost.lost_at).total_seconds() / 3600
    if -24 <= hours <= 48:
        return 1.0
    if hours < 0:
        return 0.5 - min(abs(hours) / (24 * RETRIEVAL_TOLERANCE_DAYS), 1) * 0.25
    return max(0.35, 1.0 - (hours - 48) / (24 * 21))


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


def model_fit(lost: LostFacts, found: FoundFacts) -> float | None:
    if found.model:
        return model_similarity(lost.model, found.model)
    for options, support in ((found.model_candidates, 0.7), (found.less_likely_models, 0.58)):
        if any((model_similarity(lost.model, option) or 0.0) >= 0.85 for option in options):
            return support
    return None


def color_similarity(left: str | None, right: str | None) -> float | None:
    a, b = ((color or "").strip().casefold().replace("grey", "gray") for color in (left, right))
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if "multicolor" in (a, b):
        return 0.5
    return 0.6 if any(a in group and b in group for group in COLOR_GROUPS) else 0.0


def attribute_score(
    lost: LostFacts, found: FoundFacts, color_frequency: float | None = None
) -> float:
    # The four fixed contributions leave unknown observations at the midpoint.
    # Model and inferred brand share a signal, so do not count the inference twice.
    similarities = {
        "brand": _brand_similarity(lost, found) if lost.brand and found.brand else None,
        "model": model_fit(lost, found),
        "color": color_similarity(lost.color, found.color),
        "material": model_similarity(lost.material, found.material),
    }
    reliability = found.reliability or {}
    color_weight = 0.12 if color_frequency is None else 0.20 - 0.14 * color_frequency
    weights = {"brand": 0.28, "model": 0.42, "color": color_weight, "material": 0.10}
    return 0.5 + sum(
        weights[name] * reliability.get(name, 1.0) * (similarity - 0.5)
        for name, similarity in similarities.items()
        if similarity is not None
    )


def score(
    lost: LostFacts, found: FoundFacts, semantic: float | None, color_frequency: float | None = None
) -> dict[str, float]:
    reliability = (found.reliability or {}).get("category", 1.0)
    parts = {
        "category": 0.5 + reliability * (category_score(lost, found) - 0.5),
        "location": location_score(lost, found),
        "time": time_score(lost, found),
        "attributes": attribute_score(lost, found, color_frequency),
        "semantic": 0.5 if semantic is None else max(0.0, min(1.0, semantic)),
    }
    points = {name: round(value * WEIGHTS[name], 1) for name, value in parts.items()}
    points["total"] = round(sum(points.values()), 2)
    return points


def plausible(lost: LostFacts, found: FoundFacts, semantic: float | None) -> bool:
    """Exclude only corroborated mismatches. Uncertainty keeps the candidate in play."""
    category_reliability = (found.reliability or {}).get("category", 1.0)
    return (
        semantic is None
        or semantic > 0.15
        or category_score(lost, found) > 0.2
        or category_reliability < 0.7
        or attribute_score(lost, found) > 0.5
    )
