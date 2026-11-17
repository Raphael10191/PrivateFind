"""Decide claims from the match score and the owner's evidence for private details."""

import re
from dataclasses import dataclass, field

from app.shared.vocab import CRITICAL_TYPES, GENERIC_CATEGORIES, STRENGTH_WEIGHT

APPROVE_AT = 75
REVIEW_AT = 50
SIMILARITY_MATCH = 0.6
DETAIL_COUNT = 2


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
    """Compare exact identifiers and score the two strongest confirmed details."""
    strongest = sorted(attrs, key=_weight, reverse=True)
    possible = sum(map(_weight, strongest[:DETAIL_COUNT]))
    conflict = False
    used_attrs: set[int] = set()
    used_values: set[str] = set()
    results: dict[int, tuple[str, int | None, float | None]] = {
        i: ("unmatched", None, None) for i in range(len(evidence))
    }

    for i, ev in enumerate(evidence):
        if ev.type not in CRITICAL_TYPES:
            continue
        candidates = [attr for attr in strongest if comparable(attr, ev)]
        match = next((attr for attr in candidates if critical_matches(attr.value, ev.value)), None)
        if match is not None:
            results[i] = ("match", match.id, 1.0)
            used_attrs.add(match.id)
            used_values.add(" ".join(ev.value.casefold().split()))
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
    for attr, i, sim in sorted(pairs, key=lambda pair: (_weight(pair[0]), pair[2]), reverse=True):
        value = " ".join(evidence[i].value.casefold().split())
        if sim >= SIMILARITY_MATCH and attr.id not in used_attrs and value not in used_values:
            results[i] = ("match", attr.id, sim)
            used_attrs.add(attr.id)
            used_values.add(value)

    for attr, i, sim in sorted(pairs, key=lambda pair: pair[2], reverse=True):
        if results[i][0] == "unmatched" and sim < SIMILARITY_MATCH:
            results[i] = ("mismatch", attr.id, sim)

    matched = [_weight(attr) for attr in strongest if attr.id in used_attrs][:DETAIL_COUNT]
    detail_score = 100 * sum(matched) / possible if possible else 0
    score = round(0.6 * match_score + 0.4 * detail_score)
    if conflict:
        decision = "rejected"
    elif category in GENERIC_CATEGORIES:
        decision = "in_review"
    elif score >= APPROVE_AT:
        decision = "approved"
    elif score >= REVIEW_AT:
        decision = "in_review"
    else:
        decision = "rejected"
    return Verdict(decision, score, conflict, results)


MESSAGES = {
    "pending": "Your claim is waiting to be checked.",
    "approved": "Ownership verified. Use the pickup code at the locker.",
    "in_review": "Thanks. An administrator will review your claim.",
    "rejected": "We could not verify that this item is yours.",  # never says which detail
}
