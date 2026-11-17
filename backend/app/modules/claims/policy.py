"""Decide claims from the match score and the owner's evidence for private details."""

import re
from dataclasses import dataclass, field
from itertools import product

from app.shared.vocab import CRITICAL_TYPES, GENERIC_CATEGORIES, STRENGTH_WEIGHT

APPROVE_AT = 75
REVIEW_AT = 50
SIMILARITY_MATCH = 0.6
TOP_N = 2


@dataclass
class Attr:
    id: int
    type: str
    value: str
    strength: str | None


@dataclass
class Evidence:
    type: str
    value: str


@dataclass
class Verdict:
    decision: str  # APPROVED | IN_REVIEW | REJECTED
    score: int
    critical_conflict: bool
    detail_score: float
    # evidence index -> (result, matched attribute id, similarity)
    results: dict[int, tuple[str, int | None, float | None]] = field(default_factory=dict)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def critical_matches(attr_value: str, claimed: str) -> bool:
    """Serial suffix: the claimed digits must end with the stored suffix."""
    want, got = _digits(attr_value), _digits(claimed)
    return bool(want) and len(got) >= len(want) and got.endswith(want)


def comparable(attr: Attr, ev: Evidence) -> bool:
    return (
        attr.type == ev.type if attr.type in CRITICAL_TYPES or ev.type in CRITICAL_TYPES else True
    )


def _weight(attr: Attr) -> int:
    return STRENGTH_WEIGHT[attr.strength or "generic"]


def verify(
    category: str | None,
    attrs: list[Attr],
    evidence: list[Evidence],
    similarity: dict[tuple[int, int], float],
    match_score: float,
) -> Verdict:
    """Compare exact identifiers and score only the two strongest stored attributes."""
    strongest = sorted(attrs, key=lambda attr: (-_weight(attr), attr.id))
    top = strongest[:TOP_N]
    possible = sum(map(_weight, top))
    values = [" ".join(ev.value.casefold().split()) for ev in evidence]
    conflict = False
    used_attrs: set[int] = set()
    used_values: set[str] = set()
    results: dict[int, tuple[str, int | None, float | None]] = {
        i: ("unmatched", None, None) for i in range(len(evidence))
    }

    def record_match(attr: Attr, index: int, sim: float) -> None:
        results[index] = ("match", attr.id, sim)
        used_attrs.add(attr.id)
        used_values.add(values[index])

    for i, ev in enumerate(evidence):
        if ev.type not in CRITICAL_TYPES:
            continue
        candidates = [attr for attr in strongest if comparable(attr, ev)]
        match = next((attr for attr in candidates if critical_matches(attr.value, ev.value)), None)
        if match is not None:
            record_match(match, i, 1.0)
        elif candidates:
            results[i] = ("conflict", candidates[0].id, 0.0)
            conflict = True

    pairs = [
        (attr, i, sim)
        for attr in strongest
        if attr.type not in CRITICAL_TYPES
        for i, ev in enumerate(evidence)
        if comparable(attr, ev) and (sim := similarity.get((attr.id, i))) is not None
    ]
    # Check both top attributes together so a shared candidate cannot hide a valid pair.
    options: dict[int, list[tuple[Attr, int, float] | None]] = {
        attr.id: [None] for attr in top if attr.type not in CRITICAL_TYPES
    }
    for attr, i, sim in pairs:
        if attr.id in options and sim >= SIMILARITY_MATCH and values[i] not in used_values:
            options[attr.id].append((attr, i, sim))
    best = []
    best_rank = (0, 0.0)
    for choice in product(*options.values()):
        matches = [pair for pair in choice if pair is not None]
        if len({values[index] for _, index, _ in matches}) != len(matches):
            continue
        rank = (sum(_weight(attr) for attr, _, _ in matches), sum(sim for _, _, sim in matches))
        if rank > best_rank:
            best, best_rank = matches, rank
    for attr, i, sim in best:
        record_match(attr, i, sim)

    for attr, i, sim in sorted(pairs, key=lambda pair: pair[2], reverse=True):
        if results[i][0] != "unmatched":
            continue
        if sim < SIMILARITY_MATCH:
            results[i] = ("mismatch", attr.id, sim)
        elif attr.id not in used_attrs and values[i] not in used_values:
            record_match(attr, i, sim)

    matched = sum(_weight(attr) for attr in top if attr.id in used_attrs)
    detail_score = 100 * matched / possible if possible else 0
    score = round(0.6 * match_score + 0.4 * detail_score)
    if conflict or score < REVIEW_AT:
        decision = "rejected"
    elif score >= APPROVE_AT and category not in GENERIC_CATEGORIES:
        decision = "approved"
    else:
        decision = "in_review"
    return Verdict(decision, score, conflict, detail_score, results)


MESSAGES = {
    "pending": "Your claim is waiting to be checked.",
    "approved": "Ownership verified. Use the pickup code at the locker.",
    "in_review": "Thanks. An administrator will review your claim.",
    "rejected": "We could not verify that this item is yours.",  # never says which detail
}
