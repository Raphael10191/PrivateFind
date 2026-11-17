from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.db import utcnow
from app.modules.claims import policy, service
from app.modules.found_items.models import FoundItem, ItemAttribute
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import AIError, PhotoFinding, set_ai_provider
from tests.conftest import deposit_and_store

BACK = "Glass missing beside the rear camera"
FRONT = "Star-shaped crack at the top of the screen"
GOOD = [{"type": "damage", "value": FRONT}]
OPERATOR_APPROVAL = {
    "decision": "approve",
    "proof": "dated_identifier_record",
    "note": "Compared the serial with a dated device listing.",
}
HANDOVER = {
    "decision": "handed_over",
    "proof": "in_person_low_risk",
    "note": "Checked the account holder in person and handed over the cap.",
}


def finding(quote, part="back", *, status="confirmed", distinctive=True, kind="damage"):
    return PhotoFinding(
        quote=quote,
        part=part,
        status=status,
        kind=kind,
        distinctive=distinctive,
        photo_index=0 if status in ("confirmed", "contradicted") else None,
        observation=f"Visible {quote}",
    )


def visual_provider(*, fail=False):
    ai = MockAIProvider()

    async def observe(photos, text):
        assert photos
        if fail:
            raise AIError("Simulated photo service failure")
        return [
            finding(quote, part)
            for quote, part in ((BACK, "back"), (FRONT, "front"))
            if quote in text
        ]

    ai.verify_photos = AsyncMock(side_effect=observe)
    set_ai_provider(ai)
    return ai


async def make_report(owner, *, description, category="phone", **fields):
    data = {
        "category": category,
        "location": "library",
        "lost_at": (utcnow() - timedelta(hours=2)).isoformat(),
        "description": description,
        **fields,
    }
    response = await owner.post("/api/lost-reports", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def setup_candidate(client, owner, locker, description=BACK, *, category="phone"):
    _, headers = locker
    visual_provider()
    item_id = await deposit_and_store(
        client, headers, note="Purple Apple iPhone" if category == "phone" else "Black cap"
    )
    report_id = await make_report(owner, description=description, category=category)
    candidates = (await owner.get(f"/api/lost-reports/{report_id}/candidates?refresh=false")).json()
    assert candidates[0]["found_item_id"] == item_id
    return item_id, report_id, headers


async def claim(c, report_id, item_id, evidence=None, **more):
    return await c.post(
        "/api/claims",
        json={"lost_report_id": report_id, "found_item_id": item_id, "evidence": evidence, **more},
    )


@pytest.mark.parametrize(
    ("category", "initial", "additional", "expected"),
    [
        pytest.param(
            "phone",
            [finding(BACK), finding(FRONT, "front")],
            [],
            ("verified", None),
            id="purple-iphone-distinct-surfaces",
        ),
        pytest.param(
            "phone",
            [finding("black phone", kind="common")],
            [],
            ("needs_more_evidence", "device_record"),
            id="undamaged-iphone",
        ),
        pytest.param(
            "clothing",
            [finding("black cap", kind="common")],
            [],
            ("unresolved", "contact_operator"),
            id="identical-caps",
        ),
        pytest.param(
            "keys",
            [finding("fox charm", status="unobservable")],
            [],
            ("unresolved", "contact_operator"),
            id="keys-sparse-photos",
        ),
        pytest.param(
            "headphones", [], [], ("needs_more_evidence", "device_record"), id="headphones-serial"
        ),
        pytest.param(
            "bag",
            [finding("Repair on the shoulder strap", "strap")],
            [],
            ("needs_more_evidence", "another_detail"),
            id="backpack-one-repair",
        ),
        pytest.param(
            "phone",
            [finding(BACK, status="unobservable")],
            [],
            ("needs_more_evidence", "device_record"),
            id="blurred-photo",
        ),
        pytest.param(
            "phone",
            [],
            [finding(BACK), finding(FRONT, "front")],
            ("needs_more_evidence", "device_record"),
            id="post-listing-guess",
        ),
        pytest.param(
            "phone",
            [finding(BACK)],
            [finding("Missing glass by camera")],
            ("needs_more_evidence", "another_detail"),
            id="same-mark-paraphrased",
        ),
        pytest.param(
            "phone",
            [finding(BACK)],
            [finding(BACK, "front")],
            ("needs_more_evidence", "another_detail"),
            id="same-quote-relabelled",
        ),
        pytest.param(
            "phone",
            [finding("Back is pristine", status="contradicted")],
            [],
            ("refuted", None),
            id="clear-conflict",
        ),
    ],
)
def test_adaptive_verification_scenarios(category, initial, additional, expected):
    verdict = policy.assess(initial, additional, category=category)
    assert (verdict.state, verdict.action) == expected


def test_typed_identifier_alone_cannot_authorize_pickup():
    kwargs = {"category": "headphones", "trusted_identifier": "sn77485633"}
    assert (
        policy.assess([], [], identifiers=("sn77485633",), **kwargs).state == "needs_more_evidence"
    )
    assert policy.assess([], [], identifiers=("xx77485633",), **kwargs).state == "refuted"


def test_visual_support_is_grounded_in_claim_and_photo():
    with pytest.raises(AIError):
        service._grounded_findings("a blue phone", [finding("cat sticker")], 1)
    with pytest.raises(AIError):
        service._grounded_findings(BACK, [finding(BACK).model_copy(update={"photo_index": 2})], 1)
    guess = "Maybe a red fox charm"
    result = service._grounded_findings(guess, [finding(guess)], 1)
    assert result[0].status == "ambiguous"


def test_guess_stays_ambiguous_if_the_model_omits_the_qualifier():
    text = "Maybe there is a red fox charm."
    result = service._grounded_findings(text, [finding("red fox charm")], 1)
    assert result[0].status == "ambiguous"


async def test_approved_claim_to_pickup(client, owner, session, locker):
    item_id, report_id, headers = await setup_candidate(client, owner, locker, BACK + ". " + FRONT)
    response = await claim(owner, report_id, item_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verification_state"] == "verified"
    assert len(body["pickup_code"]) == 6
    pickup = await client.post(
        "/api/device/codes/validate",
        headers=headers,
        json={"device_id": "locker_01", "code": body["pickup_code"]},
    )
    assert pickup.json()["authorized"] and pickup.json()["action"] == "pickup"
    state = await client.post(
        f"/api/device/compartments/{pickup.json()['compartment']}/state",
        headers=headers,
        json={"device_id": "locker_01", "occupied": False},
    )
    assert state.json()["state"] == "free"
    assert (await session.get(FoundItem, item_id)).status == "returned"
    assert (await owner.get(f"/api/lost-reports/{report_id}")).json()["status"] == "resolved"


async def test_retries_retain_original_and_supplemental_evidence(client, owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    first = (await claim(owner, report_id, item_id, description="The case is purple")).json()
    assert first["next_action"] == "another_detail"
    second = (await claim(owner, report_id, item_id, GOOD)).json()
    assert second["id"] == first["id"] and second["verification_state"] == "verified"
    assert "evidence" not in second
    reviewed = (await admin.get(f"/api/admin/claims/{second['id']}")).json()
    assert [row["value"] for row in reviewed["evidence"] if row["type"] == "submission"] == [
        "The case is purple",
        FRONT,
    ]


async def test_review_then_admin_approve_and_pickup_code(client, owner, admin, locker, session):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Plain iPhone")
    item = await session.get(FoundItem, item_id)
    item.category = "headphones"
    item.attributes.append(
        ItemAttribute(
            name="serial_suffix", value="SN77485633", source="admin", visibility="private"
        )
    )
    await session.commit()
    response = await claim(owner, report_id, item_id, description="Serial number SN77485633")
    claim_body = response.json()
    assert claim_body["next_action"] == "device_record" and claim_body["pickup_code"] is None
    url = f"/api/admin/claims/{claim_body['id']}/decision"
    assert (await admin.post(url, json={"decision": "approve"})).status_code == 422
    assert (await owner.post(url, json=OPERATOR_APPROVAL)).status_code == 403
    assert (await admin.post(url, json=OPERATOR_APPROVAL)).json()[
        "verification_state"
    ] == "verified"
    assert (await owner.post(f"/api/claims/{claim_body['id']}/pickup-code")).status_code == 200


async def test_public_details_and_rate_limit(client, owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Purple iPhone")
    for _ in range(3):
        response = await claim(owner, report_id, item_id, description="Apple phone, purple")
        assert response.status_code == 201 and response.json()["pickup_code"] is None
    assert (await claim(owner, report_id, item_id)).status_code == 429


async def test_claim_requires_candidate(client, owner, other_owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    late_report = await make_report(
        other_owner,
        description="An Apple phone",
        lost_at=(utcnow() + timedelta(days=8)).isoformat(),
    )
    assert (await claim(other_owner, late_report, item_id)).json()["error"][
        "code"
    ] == "not_a_candidate"
    assert (await claim(other_owner, report_id, item_id)).status_code == 404


async def test_competing_claims_block_automatic_authorization(
    client, owner, other_owner, admin, locker
):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    second = await make_report(other_owner, description="Purple iPhone")
    competing = (await claim(other_owner, second, item_id)).json()
    initial = (await claim(owner, report_id, item_id, GOOD)).json()
    assert initial["verification_state"] == "unresolved" and initial["pickup_code"] is None
    url = f"/api/admin/claims/{initial['id']}/decision"
    assert (await admin.post(url, json=OPERATOR_APPROVAL)).json()["status"] == "approved"
    assert (await other_owner.post(f"/api/claims/{competing['id']}/pickup-code")).status_code == 409
    assert (await owner.post(f"/api/claims/{initial['id']}/pickup-code")).status_code == 200


async def test_low_risk_handover_requires_operator_and_no_competing_claim(
    client, owner, other_owner, admin, locker, session
):
    item_id, report_id, _ = await setup_candidate(
        client, owner, locker, "Black cap", category="clothing"
    )
    item = await session.get(FoundItem, item_id)
    item.category = "clothing"
    await session.commit()
    second = await make_report(other_owner, description="Black cap", category="clothing")
    current = (await claim(owner, report_id, item_id)).json()
    competing = (await claim(other_owner, second, item_id)).json()
    url = f"/api/admin/claims/{current['id']}/decision"
    assert (await admin.post(url, json=HANDOVER)).status_code == 409
    assert (
        await admin.post(
            f"/api/admin/claims/{competing['id']}/decision",
            json={"decision": "reject", "note": "The claimant withdrew during the visit."},
        )
    ).status_code == 200
    final = await admin.post(url, json=HANDOVER)
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "handed_over" and final.json()["pickup_code"] is None
    assert (await owner.post(f"/api/claims/{current['id']}/pickup-code")).status_code == 409
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2
    entries = (await admin.get("/api/admin/audit")).json()
    assert next(e for e in entries if e["action"] == "claim_decided")["actor_type"] == "admin"


async def test_outage_and_legacy_disclosures_do_not_issue_codes(client, owner, locker, session):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, BACK + ". " + FRONT)
    visual_provider(fail=True)
    failed = (await claim(owner, report_id, item_id)).json()
    assert failed["next_action"] == "retry_photo_check" and failed["pickup_code"] is None
    visual_provider()
    item = await session.get(FoundItem, item_id)
    item.owner_details_exposed = True
    await session.commit()
    exposed = (await claim(owner, report_id, item_id)).json()
    assert exposed["verification_state"] == "unresolved" and exposed["pickup_code"] is None


async def test_one_report_cannot_authorize_two_items(client, owner, locker):
    item_id, report_id, headers = await setup_candidate(client, owner, locker, BACK + ". " + FRONT)
    other_item = await deposit_and_store(client, headers, note="Purple Apple iPhone")
    assert (await claim(owner, report_id, item_id)).json()["pickup_code"]
    second = await claim(owner, report_id, other_item)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "report_already_resolved"


async def test_photo_claim_with_conflicting_confirmations_stays_unresolved():
    supported = [finding(BACK), finding(FRONT, "front")]
    conflicts = [finding("Blue bezel", status="contradicted", kind="common")]
    result = policy.assess(supported, conflicts, category="phone")
    assert (result.state, result.action) == ("unresolved", "contact_operator")


async def test_phone_cannot_use_low_risk_handover(client, owner, admin, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Purple iPhone")
    body = (await claim(owner, report_id, item_id)).json()
    response = await admin.post(f"/api/admin/claims/{body['id']}/decision", json=HANDOVER)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "handover_unavailable"


async def test_post_listing_details_alone_cannot_authorize_pickup(client, owner, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker, "Plain iPhone")
    first = (await claim(owner, report_id, item_id, description=BACK + ". " + FRONT)).json()
    assert first["next_action"] == "device_record"
    assert first["pickup_code"] is None


@pytest.mark.parametrize("status", ["confirmed", "contradicted"])
def test_exact_model_guess_is_not_a_verified_finding(status):
    reported = "black iPhone 14 with a magnetic ring"
    visual = service._grounded_findings(
        reported,
        [
            finding("iPhone 14", status=status, kind="model"),
            finding("magnetic ring", kind="common", distinctive=False),
        ],
        1,
    )
    assert visual[0].status == "unobservable"
    assert visual[1].status == "confirmed"
    assert policy.assess(visual, [], category="phone").action == "device_record"
