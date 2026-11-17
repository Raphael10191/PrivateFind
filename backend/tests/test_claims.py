from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.modules.claims import policy, service
from app.modules.found_items.models import FoundItem
from app.modules.lost_reports.models import LostReport
from app.modules.matching.models import MatchCandidate
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import set_ai_provider
from tests.conftest import deposit_and_store

# ---------- policy ----------

ATTRS = [
    policy.Attr(1, "serial_suffix", "4821", "strong"),
    policy.Attr(2, "sticker_or_mark", "cat sticker", "distinctive"),
]


def verify(evidence, sims=None, category="phone", attrs=ATTRS, match_score=80):
    ev = [policy.Evidence(t, v) for t, v in evidence]
    return policy.verify(category, attrs, ev, sims or {}, match_score)


def test_strong_evidence_approved():
    v = verify([("serial_suffix", "SN-99214821"), ("sticker_or_mark", "cat")], {(2, 1): 0.9})
    assert (v.decision, v.score) == ("approved", 88)


def test_partial_evidence_goes_to_review_or_rejected():
    v = verify([("serial_suffix", "4821")])
    assert (v.decision, v.score) == ("in_review", 72)
    v = verify([("sticker_or_mark", "cat")], {(2, 0): 0.9}, match_score=50)
    assert (v.decision, v.score) == ("rejected", 46)


def test_wrong_serial_is_critical_conflict():
    v = verify([("serial_suffix", "1234"), ("sticker_or_mark", "cat")], {(2, 1): 0.9})
    assert v.decision == "rejected" and v.critical_conflict
    assert v.results[0][0] == "conflict"


def test_generic_item_never_auto_approved():
    attrs = [policy.Attr(1, "damage", "bent handle", "distinctive")]
    v = verify(
        [("damage", "bent handle")],
        {(1, 0): 1.0},
        category="umbrella",
        attrs=attrs,
        match_score=100,
    )
    assert (v.decision, v.score) == ("in_review", 100)
    assert verify([("other", "plain")], category="umbrella", attrs=[]).decision == "rejected"


def test_low_similarity_does_not_count():
    v = verify([("serial_suffix", "4821"), ("sticker_or_mark", "dog")], {(2, 1): 0.2})
    assert v.score == 72 and v.results[1][0] == "mismatch"


@pytest.mark.parametrize(
    ("text", "match_score", "similarity", "expected"),
    [
        ("schwarzes Handy", 70, 0.4, ("rejected", 42, 0)),
        ("Auto als Hintergrund", 92, 0.95, ("approved", 75, 50)),
    ],
)
def test_specific_wallpaper_can_verify_where_generic_text_cannot(
    text, match_score, similarity, expected
):
    attrs = [
        policy.Attr(1, "sticker_or_mark", "rally car wallpaper", "distinctive"),
        policy.Attr(2, "damage", "scratched back", "distinctive"),
    ]
    verdict = verify([("other", text)], {(1, 0): similarity}, attrs=attrs, match_score=match_score)
    assert (verdict.decision, verdict.score, verdict.detail_score) == expected


def test_a_lower_weight_detail_cannot_substitute_for_a_top_attribute():
    attrs = [
        policy.Attr(1, "engraving", "engraved initials", "strong"),
        policy.Attr(2, "damage", "scratched back", "distinctive"),
        policy.Attr(3, "accessory", "hard case", "generic"),
    ]
    verdict = verify([("other", "hard case")], {(3, 0): 1}, attrs=attrs, match_score=92)
    assert (verdict.decision, verdict.score, verdict.detail_score) == ("in_review", 55, 0)


def test_top_attributes_can_use_different_evidence_when_best_match_overlaps():
    attrs = [
        policy.Attr(1, "damage", "scratched screen", "distinctive"),
        policy.Attr(2, "damage", "scratched back", "distinctive"),
    ]
    verdict = verify(
        [("other", "scratch on back"), ("other", "screen damage")],
        {(1, 0): 0.97, (1, 1): 0.8, (2, 0): 0.9},
        attrs=attrs,
    )
    assert (verdict.decision, verdict.detail_score) == ("approved", 100)
    assert verdict.results == {0: ("match", 2, 0.9), 1: ("match", 1, 0.8)}


def test_split_free_text_and_report_to_eight_details_with_typed_serial_preserved():
    evidence = service._claim_evidence(
        [
            {"type": "other", "value": "Auto; Kratzer\nGravur und Band, Aufkleber"},
            {"type": "serial_suffix", "value": "4821"},
        ],
        "Auto mit Hülle and Display with Name",
    )
    assert [e.value for e in evidence] == [
        "4821",
        "Auto",
        "Kratzer",
        "Gravur",
        "Band",
        "Aufkleber",
        "Hülle",
        "Display",
    ]
    assert [e.type for e in evidence] == ["serial_suffix"] + ["other"] * 7


async def test_provider_without_batch_method_uses_compare_texts_with_correct_indices():
    compare = AsyncMock(return_value=[0.9, 0.2])
    set_ai_provider(SimpleNamespace(compare_texts=compare))
    evidence = [
        policy.Evidence("other", "Auto"),
        policy.Evidence("serial_suffix", "4821"),
        policy.Evidence("damage", "Cracked glass"),
    ]
    assert await service._similarities(ATTRS, evidence) == {(2, 0): 0.9, (2, 2): 0.2}
    compare.assert_awaited_once_with("cat sticker", ["Auto", "Cracked glass"])


@pytest.mark.parametrize(
    ("match_score", "expected_score", "decision"),
    [(58, 75, "approved"), (57, 74, "in_review"), (16, 50, "in_review"), (15, 49, "rejected")],
)
def test_combined_score_thresholds(match_score, expected_score, decision):
    attrs = [
        policy.Attr(1, "damage", "cracked back", "distinctive"),
        policy.Attr(2, "sticker_or_mark", "car wallpaper", "distinctive"),
        policy.Attr(3, "accessory", "black case", "distinctive"),
    ]
    v = verify(
        [("other", "Kratzer hinten"), ("accessory", "Auto als Hintergrund")],
        {(1, 0): 0.9, (2, 1): 0.9},
        attrs=attrs,
        match_score=match_score,
    )
    assert (v.decision, v.score) == (decision, expected_score)


def test_repeated_evidence_can_only_confirm_one_detail():
    attrs = [
        policy.Attr(1, "damage", "scratched screen", "distinctive"),
        policy.Attr(2, "damage", "scratched back", "distinctive"),
    ]
    v = verify(
        [("damage", "scratch"), ("other", " Scratch ")],
        {(1, 0): 0.9, (2, 1): 0.9},
        attrs=attrs,
    )
    assert (v.decision, v.score) == ("in_review", 68)


def test_wrong_serial_remains_a_conflict_alongside_correct_evidence():
    v = verify(
        [("serial_suffix", "4821"), ("serial_suffix", "1234"), ("other", "cat")],
        {(2, 2): 1.0},
        match_score=100,
    )
    assert v.decision == "rejected" and v.critical_conflict


# ---------- API ----------

GOOD = [
    {"type": "serial_suffix", "value": "4821"},
    {"type": "sticker_or_mark", "value": "cat sticker on the back"},
]


async def setup_candidate(
    client, owner, locker, description="Black Samsung phone with a cat sticker"
):
    """Stored phone + the owner's lost report that lists it as a candidate."""
    _, h = locker
    item_id = await deposit_and_store(client, h)
    report = {
        "category": "phone",
        "location": "library",
        "lost_at": (utcnow() - timedelta(hours=2)).isoformat(),
        "color": "black",
        "brand": "Samsung",
        "description": description,
    }
    report_id = (await owner.post("/api/lost-reports", json=report)).json()["id"]
    cands = (await owner.get(f"/api/lost-reports/{report_id}/candidates")).json()
    assert cands[0]["found_item_id"] == item_id
    return item_id, report_id, h


async def claim(c, report_id, item_id, evidence):
    return await c.post(
        "/api/claims",
        json={"lost_report_id": report_id, "found_item_id": item_id, "evidence": evidence},
    )


async def test_approved_claim_to_pickup(client, owner, session, locker):
    item_id, report_id, h = await setup_candidate(client, owner, locker)

    r = await claim(owner, report_id, item_id, GOOD)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "approved" and len(body["pickup_code"]) == 6

    # Locker: pickup code opens the compartment, owner takes the item, presses #
    r = await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": body["pickup_code"]},
        headers=h,
    )
    assert r.json()["action"] == "pickup" and r.json()["authorized"] is True
    r = await client.post(
        f"/api/device/compartments/{r.json()['compartment']}/state",
        json={"device_id": "locker_01", "occupied": False},
        headers=h,
    )
    assert r.json()["state"] == "free"

    item = await session.scalar(select(FoundItem).where(FoundItem.id == item_id))
    assert item.status == "returned"
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2
    assert (await owner.get(f"/api/lost-reports/{report_id}")).json()["status"] == "resolved"


async def test_rejected_message_hides_reason(client, owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    r = await claim(owner, report_id, item_id, [{"type": "serial_suffix", "value": "0000"}])
    body = r.json()
    assert body["status"] == "rejected" and "serial" not in body["message"].lower()
    assert body["pickup_code"] is None


async def test_cooldown_after_three_failures(client, owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    bad = [{"type": "serial_suffix", "value": "0000"}]
    for _ in range(3):
        assert (await claim(owner, report_id, item_id, bad)).json()["status"] == "rejected"
    r = await claim(owner, report_id, item_id, GOOD)
    assert r.status_code == 429 and r.json()["error"]["code"] == "claim_cooldown"


async def test_claim_requires_candidate(client, owner, other_owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    report = {
        "category": "wallet",
        "location": "library",
        "lost_at": utcnow().isoformat(),
        "description": "my wallet",
    }
    other_report = (await other_owner.post("/api/lost-reports", json=report)).json()["id"]
    r = await claim(other_owner, other_report, item_id, GOOD)  # item did not qualify
    assert r.json()["error"]["code"] == "not_a_candidate"
    assert (await claim(other_owner, report_id, item_id, GOOD)).status_code == 404  # not theirs


async def test_review_then_admin_approve_and_pickup_code(client, owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Black Samsung phone")
    r = await claim(owner, report_id, item_id, [{"type": "other", "value": "plain case"}])
    claim_id = r.json()["id"]
    assert r.json()["status"] == "in_review"

    queue = (await admin.get("/api/admin/claims")).json()
    assert [c["id"] for c in queue] == [claim_id]
    assert queue[0]["ownership_score"] == 60 and queue[0]["item_private_attributes"]

    r = await admin.post(f"/api/admin/claims/{claim_id}/decision", json={"decision": "approve"})
    assert r.json()["status"] == "approved"

    r = await owner.post(f"/api/claims/{claim_id}/pickup-code")
    assert r.status_code == 200 and len(r.json()["pickup_code"]) == 6
    assert (await owner.get(f"/api/claims/{claim_id}")).json()["pickup_code"] is None


async def test_first_approval_wins(client, owner, other_owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    # Second owner reports the same phone and goes to review.
    report = {
        "category": "phone",
        "location": "library",
        "lost_at": (utcnow() - timedelta(hours=1)).isoformat(),
        "description": "Black Samsung phone",
    }
    other_report = (await other_owner.post("/api/lost-reports", json=report)).json()["id"]
    await other_owner.get(f"/api/lost-reports/{other_report}/candidates")
    review = await claim(
        other_owner, other_report, item_id, [{"type": "other", "value": "plain case"}]
    )
    assert review.json()["status"] == "in_review"

    assert (await claim(owner, report_id, item_id, GOOD)).json()["status"] == "approved"

    # Competing claim was closed; the item cannot be claimed again.
    r = await admin.get(f"/api/admin/claims/{review.json()['id']}")
    assert r.json()["status"] == "rejected"
    r = await claim(other_owner, other_report, item_id, GOOD)
    assert r.json()["error"]["code"] == "item_unavailable"


async def test_admin_only(owner):
    assert (await owner.get("/api/admin/claims")).status_code == 403


async def test_photo_verification_rechecks_existing_review_and_issues_code(
    client,
    owner,
    locker,
    session,
):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Black Samsung phone")
    weak = [{"type": "other", "value": "generic description"}]
    first = (await claim(owner, report_id, item_id, weak)).json()
    assert first["status"] == "in_review"
    match = await session.scalar(
        select(MatchCandidate).where(
            MatchCandidate.lost_report_id == report_id,
            MatchCandidate.found_item_id == item_id,
        )
    )
    match.total = 90
    await session.commit()

    ai = MockAIProvider()
    ai.verify_photos = AsyncMock(return_value=[0.95, 0.25])
    set_ai_provider(ai)
    reply = await claim(owner, report_id, item_id, [{"type": "other", "value": "German Language"}])
    result = reply.json()
    assert result["id"] == first["id"]
    assert result["status"] == "approved" and len(result["pickup_code"]) == 6
    photos, details = ai.verify_photos.call_args.args
    assert len(photos) == 1 and photos[0].data.startswith(b"\xff\xd8")
    assert details == ["German Language", "Black Samsung phone"]


@pytest.mark.parametrize(
    ("match_score", "visual_score", "status"),
    [(90, 0.5, "rejected"), (90, 0.95, "approved"), (60, 0.95, "in_review")],
)
def test_visual_decision_uses_visible_proof_and_match_score(match_score, visual_score, status):
    verdict = policy.verify_photo_evidence(
        [],
        [policy.Evidence("other", "German Language")],
        {0: visual_score},
        match_score,
    )
    assert verdict.decision == status


def test_visual_proof_cannot_override_wrong_serial():
    verdict = policy.verify_photo_evidence(
        ATTRS,
        [policy.Evidence("serial_suffix", "1234"), policy.Evidence("other", "cat sticker")],
        {1: 1.0},
        100,
    )
    assert (verdict.decision, verdict.critical_conflict) == ("rejected", True)


async def test_report_evidence_is_included_in_one_batch(client, owner, admin, locker, caplog):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    ai = MockAIProvider()
    ai.verify_details = AsyncMock(wraps=ai.verify_details)
    set_ai_provider(ai)

    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = await claim(
            owner,
            report_id,
            item_id,
            [
                {"type": "serial_suffix", "value": "4821"},
                {"type": "other", "value": "blauer Rand; matte Rückseite"},
            ],
        )
    assert response.json()["status"] == "approved"
    args = ai.verify_details.call_args.args
    assert ai.verify_details.await_count == 1
    assert [row["type"] for row in args[0]] == ["sticker_or_mark"]
    assert args[1] == ["blauer Rand", "matte Rückseite", "Black Samsung phone", "a cat sticker"]
    assert (
        caplog.messages.count("[VERIFY] Matching 100 | Details 100 -> Gesamt 100 -> approved") == 1
    )
    admin_claim = await admin.get(f"/api/admin/claims/{response.json()['id']}")
    evidence = admin_claim.json()["evidence"]
    assert any(row["value"] == "a cat sticker" and row["result"] == "match" for row in evidence)


async def test_claim_still_works_for_legacy_report_without_description(
    client, owner, locker, session
):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    report = await session.get(LostReport, report_id)
    report.description = None
    await session.commit()

    response = await claim(owner, report_id, item_id, GOOD)
    assert response.status_code == 201 and response.json()["status"] == "approved"


async def test_audit_log_records_flow(client, owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    await claim(owner, report_id, item_id, GOOD)
    actions = [e["action"] for e in (await admin.get("/api/admin/audit")).json()]
    for expected in [
        "item_submitted",
        "ai_extracted",
        "compartment_opened",
        "item_stored",
        "candidates_ranked",
        "claim_submitted",
    ]:
        assert expected in actions
    assert (await owner.get("/api/admin/audit")).status_code == 403
