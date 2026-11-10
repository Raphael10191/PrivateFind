"""Ownership Verification Engine (pure functions, no I/O).

Ownership Score = matched evidence weight / total private-attribute weight x 100,
weights strong 3, distinctive 2, generic 1. Decision:
  critical conflict (e.g. wrong serial suffix) -> REJECTED
  generic item                                -> IN_REVIEW (never auto-approved)
  score >= 80                                 -> APPROVED
  50..79                                      -> IN_REVIEW
  below 50                                    -> REJECTED
The AI only supplies text similarity; this module makes the decision.
"""

import re
from dataclasses import dataclass, field

from app.shared.vocab import CRITICAL_TYPES, GENERIC_CATEGORIES, STRENGTH_WEIGHT

APPROVE_AT = 80
REVIEW_AT = 50
SIMILARITY_MATCH = 0.6


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
    return ev.type == attr.type or (ev.type == "other" and attr.type not in CRITICAL_TYPES)


def verify(
    category: str | None,
    attrs: list[Attr],
    evidence: list[Evidence],
    similarity: dict[tuple[int, int], float],
) -> Verdict:
    """`similarity[(attr.id, evidence index)]` holds AI text similarity for non-critical pairs."""
    total = sum(STRENGTH_WEIGHT[a.strength or "generic"] for a in attrs)
    matched = 0
    conflict = False
    results: dict[int, tuple[str, int | None, float | None]] = {
        i: ("unmatched", None, None) for i in range(len(evidence))
    }

    for attr in attrs:
        weight = STRENGTH_WEIGHT[attr.strength or "generic"]
        candidates = [i for i, ev in enumerate(evidence) if comparable(attr, ev)]
        if attr.type in CRITICAL_TYPES:
            for i in candidates:
                if critical_matches(attr.value, evidence[i].value):
                    results[i] = ("match", attr.id, 1.0)
                    matched += weight
                    break
                results[i] = ("conflict", attr.id, 0.0)
                conflict = True
            continue
        best = max(candidates, key=lambda i: similarity.get((attr.id, i), 0.0), default=None)
        if best is not None:
            sim = similarity.get((attr.id, best), 0.0)
            if sim >= SIMILARITY_MATCH:
                results[best] = ("match", attr.id, sim)
                matched += weight
            elif results[best][0] == "unmatched":
                results[best] = ("mismatch", attr.id, sim)

    score = round(100 * matched / total) if total else 0
    generic = category in GENERIC_CATEGORIES or all(
        (a.strength or "generic") == "generic" for a in attrs
    )
    if conflict:
        decision = "rejected"
    elif generic:
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
