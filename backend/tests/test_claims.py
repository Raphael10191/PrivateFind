from datetime import timedelta

from sqlalchemy import select

from app.core.db import utcnow
from app.modules.claims import policy
from app.modules.found_items.models import FoundItem
from tests.conftest import deposit_and_store

# ---------- policy ----------

ATTRS = [
    policy.Attr(1, "serial_suffix", "4821", "strong"),
    policy.Attr(2, "sticker_or_mark", "cat sticker", "distinctive"),
]


def verify(evidence, sims=None, category="phone", attrs=ATTRS):
    ev = [policy.Evidence(t, v) for t, v in evidence]
    return policy.verify(category, attrs, ev, sims or {})


def test_strong_evidence_approved():
    v = verify([("serial_suffix", "SN-99214821"), ("sticker_or_mark", "cat")], {(2, 1): 0.9})
    assert (v.decision, v.score) == ("approved", 100)


def test_partial_evidence_goes_to_review_or_rejected():
    assert verify([("serial_suffix", "4821")]).decision == "in_review"  # 60
    v = verify([("sticker_or_mark", "cat")], {(2, 0): 0.9})
    assert (v.decision, v.score) == ("rejected", 40)


def test_wrong_serial_is_critical_conflict():
    v = verify([("serial_suffix", "1234"), ("sticker_or_mark", "cat")], {(2, 1): 0.9})
    assert v.decision == "rejected" and v.critical_conflict
    assert v.results[0][0] == "conflict"


def test_generic_item_never_auto_approved():
    attrs = [policy.Attr(1, "damage", "bent handle", "distinctive")]
    v = verify([("damage", "bent handle")], {(1, 0): 1.0}, category="umbrella", attrs=attrs)
    assert (v.decision, v.score) == ("in_review", 100)
    assert verify([("other", "plain")], category="umbrella", attrs=[]).decision == "in_review"


def test_low_similarity_does_not_count():
    v = verify([("serial_suffix", "4821"), ("sticker_or_mark", "dog")], {(2, 1): 0.2})
    assert v.score == 60 and v.results[1][0] == "mismatch"


# ---------- API ----------

GOOD = [
    {"type": "serial_suffix", "value": "4821"},
    {"type": "sticker_or_mark", "value": "cat sticker on the back"},
]


async def setup_candidate(client, owner, locker):
    """Stored phone + the owner's lost report that lists it as a candidate."""
    _, h = locker
    item_id = await deposit_and_store(client, h)
    report = {
        "category": "phone",
        "location": "library",
        "lost_at": (utcnow() - timedelta(hours=2)).isoformat(),
        "color": "black",
        "brand": "Samsung",
        "description": "Black Samsung phone with a cat sticker",
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
        "category": "phone",
        "location": "library",
        "lost_at": utcnow().isoformat(),
        "description": "my phone",
    }
    other_report = (await other_owner.post("/api/lost-reports", json=report)).json()["id"]
    r = await claim(other_owner, other_report, item_id, GOOD)  # never saw candidates
    assert r.json()["error"]["code"] == "not_a_candidate"
    assert (await claim(other_owner, report_id, item_id, GOOD)).status_code == 404  # not theirs


async def test_review_then_admin_approve_and_pickup_code(client, owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    r = await claim(owner, report_id, item_id, [{"type": "serial_suffix", "value": "4821"}])
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
        "description": "Black Samsung phone with a cat sticker",
    }
    other_report = (await other_owner.post("/api/lost-reports", json=report)).json()["id"]
    await other_owner.get(f"/api/lost-reports/{other_report}/candidates")
    review = await claim(
        other_owner, other_report, item_id, [{"type": "serial_suffix", "value": "4821"}]
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
