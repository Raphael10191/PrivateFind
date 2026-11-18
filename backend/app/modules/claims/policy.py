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
    reason: str = ""

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
    prior = distinct_findings(initial)
    prior_quotes = {" ".join(f.quote.casefold().split()) for f in initial}
    extra = [f for f in additional if " ".join(f.quote.casefold().split()) not in prior_quotes]
    supported = distinct_findings(initial + extra)
    if trusted_identifier and any(value != trusted_identifier for value in identifiers):
        return Verdict(
            "refuted", reason="The submitted identifier conflicts with the trusted record."
        )
    disagreements = [f for f in initial + additional if f.status == "contradicted"]
    if disagreements and not supported:
        return Verdict(
            "refuted", reason="The photos contradict the claim and confirm no distinctive detail."
        )
    strong_initial = next((f for f in initial if f.strong and has_visual_support(f)), None)
    if not competing and not exposed and not disagreements:
        if strong_initial is not None:
            return Verdict(
                "verified",
                reason="Pickup code issued. The photo check confirmed a strongly identifying "
                f"detail from the original report. {_describe_finding(strong_initial)}",
            )
        if prior and len(supported) >= 2:
            details = " ".join(_describe_finding(f) for f in list(supported.values())[:2])
            return Verdict(
                "verified",
                reason="Pickup code issued. The photo check confirmed distinctive details "
                f"on two different parts, including one from the original report. {details}",
            )
    if competing:
        return Verdict(
            "unresolved", "contact_operator", "Another account has an open claim for this item."
        )
    if disagreements:
        return Verdict(
            "unresolved",
            "contact_operator",
            "The photos both support and contradict parts of the claim.",
        )
    if exposed:
        return Verdict(
            "unresolved",
            "contact_operator",
            "Identifying details may previously have been shown to owners.",
        )
    if prior:
        return Verdict(
            "needs_more_evidence",
            "another_detail",
            "The photos support a distinctive detail. More identifying evidence is needed.",
        )
    if category in DEVICE_CATEGORIES:
        return Verdict(
            "needs_more_evidence",
            "device_record",
            "The photos do not confirm a distinctive detail. "
            "An independent device record is needed.",
        )
    return Verdict(
        "unresolved", "contact_operator", "The photos do not confirm enough identifying evidence."
    )


def has_visual_support(finding: PhotoFinding) -> bool:
    return (
        finding.status == "confirmed"
        and finding.kind not in {"common", "model"}
        and finding.photo_index is not None
        and bool(finding.part and finding.distinctive and finding.observation)
    )


def distinct_findings(findings: list[PhotoFinding]) -> dict[str, PhotoFinding]:
    parts: dict[str, PhotoFinding] = {}
    observations: set[str] = set()
    for finding in findings:
        if not has_visual_support(finding):
            continue
        observation = " ".join(finding.observation.casefold().split())
        if observation not in observations:
            parts.setdefault(finding.part, finding)
            observations.add(observation)
    return parts


def _describe_finding(finding: PhotoFinding) -> str:
    assert finding.photo_index is not None
    return (
        f"“{finding.quote}” matched photo {finding.photo_index + 1} "
        f"({finding.part}): {finding.observation}."
    )


MESSAGES = {
    "pending": "Your claim is waiting to be checked.",
    "approved": "Ownership verified. Use the pickup code at the locker.",
    "revoked": "The pickup was cancelled. Return to your lost report to check other matches.",
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
