"""Ownership decisions based on corroborated evidence, independent of search rank."""

import re
from dataclasses import dataclass

from app.shared.ai.provider import PhotoFinding

LOW_RISK_CATEGORIES = {"clothing", "bottle", "umbrella", "book"}
DEVICE_CATEGORIES = {"phone", "laptop", "tablet", "headphones", "watch", "electronics"}


@dataclass(frozen=True)
class Verdict:
    state: str
    action: str | None = None

    @property
    def status(self) -> str:
        return {"verified": "approved", "refuted": "rejected"}.get(self.state, "in_review")


def normalized_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def assess(
    initial: list[PhotoFinding],
    additional: list[PhotoFinding],
    *,
    category: str | None,
    trusted_identifier: str | None = None,
    identifiers: tuple[str, ...] = (),
    competing: bool = False,
    exposed: bool = False,
) -> Verdict:
    prior = distinct_parts(initial)
    prior_quotes = {" ".join(f.quote.casefold().split()) for f in initial}
    extra = [f for f in additional if " ".join(f.quote.casefold().split()) not in prior_quotes]
    supported = distinct_parts(initial + extra)
    if trusted_identifier and any(value != trusted_identifier for value in identifiers):
        return Verdict("refuted")
    disagreements = [f for f in initial + additional if f.status == "contradicted"]
    if disagreements and not supported:
        return Verdict("refuted")
    if not competing and not exposed and not disagreements and prior and len(supported) >= 2:
        return Verdict("verified")
    if competing or disagreements or exposed:
        return Verdict("unresolved", "contact_operator")
    if prior:
        return Verdict("needs_more_evidence", "another_detail")
    if category in DEVICE_CATEGORIES:
        return Verdict("needs_more_evidence", "device_record")
    return Verdict("unresolved", "contact_operator")


def distinct_parts(findings: list[PhotoFinding]) -> set[str]:
    parts: set[str] = set()
    observations: set[str] = set()
    for f in findings:
        if (
            f.status != "confirmed"
            or f.kind in {"common", "model"}
            or not (f.part and f.distinctive and f.observation)
        ):
            continue
        observation = " ".join(f.observation.casefold().split())
        if observation not in observations:
            parts.add(f.part)
            observations.add(observation)
    return parts


MESSAGES = {
    "pending": "Your claim is waiting to be checked.",
    "approved": "Ownership verified. Use the pickup code at the locker.",
    "in_review": "Contact the locker operator to discuss your claim.",
    "rejected": "We could not verify this claim.",
    "handed_over": "The locker operator recorded an in-person handover.",
}
NEXT_ACTION_MESSAGES = {
    "another_detail": "Add one more distinctive detail or contact the locker operator.",
    "retry_photo_check": "Photo check unavailable. Try again or contact the locker operator.",
    "device_record": "Bring a purchase record or device listing to the locker operator.",
    "contact_operator": "Contact the locker operator to discuss your claim.",
}
