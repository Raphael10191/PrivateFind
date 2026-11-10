"""Integration checks for Simon's relationships and Raphael's wire format."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.claims.models import Claim
from app.modules.found_items.models import FoundItem
from app.modules.locker.models import AccessCode
from tests.conftest import deposit
from tests.test_claims import GOOD, claim, setup_candidate


@pytest.mark.parametrize("validate_path", ["/api/device/codes/validate", "/locker/validate"])
async def test_firmware_contract_and_device_id(client, session, validate_path):
    from app.modules.locker.service import create_locker

    _, key = await create_locker(session, "L1", "Demo", "library")
    headers = {"X-Device-Key": key}
    data = (await deposit(client)).json()
    body = {"device_id": "locker_01", "code": data["deposit_code"]}
    wrong = await client.post(
        validate_path, headers=headers, json={**body, "device_id": "another_locker"}
    )
    assert wrong.status_code == 401
    response = await client.post(validate_path, headers=headers, json=body)
    assert response.json() == {"authorized": True, "compartment": 1, "action": "deposit"}
    # Exact fragments the unchanged sketch checks before moving its servo.
    for fragment in ('"authorized":true', '"compartment":1', '"action":"deposit"'):
        assert fragment in response.text
    state = await client.post(
        "/api/device/compartments/1/state",
        headers=headers,
        json={"device_id": "locker_01", "occupied": True},
    )
    assert state.json() == {"compartment": 1, "state": "occupied"}
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 0


async def test_expired_history_does_not_cancel_next_deposit(client, session, locker):
    await deposit(client)
    old = await session.scalar(select(AccessCode))
    old.expires_at -= timedelta(hours=1)
    await session.commit()
    data = (await deposit(client)).json()
    response = await client.post(
        "/api/device/codes/validate",
        headers=locker[1],
        json={"device_id": "locker_01", "code": data["deposit_code"]},
    )
    assert response.json()["authorized"] is True


async def test_match_refresh_preserves_claim(client, owner, session, locker):
    item_id, report_id, _ = await setup_candidate(client, owner, locker)
    review = await claim(owner, report_id, item_id, [{"type": "serial_suffix", "value": "4821"}])
    claim_id = review.json()["id"]
    before = await session.get(Claim, claim_id)
    match_id = before.match_id
    await owner.get(f"/api/lost-reports/{report_id}/candidates")
    session.expire_all()
    assert (await session.get(Claim, claim_id)).match_id == match_id


async def test_pickup_replacement_and_admin_attribute_correction(
    client, owner, admin, session, locker
):
    item_id, report_id, headers = await setup_candidate(client, owner, locker)
    approved = (await claim(owner, report_id, item_id, GOOD)).json()
    code = await session.scalar(select(AccessCode).where(AccessCode.purpose == "pickup"))
    code.expires_at -= timedelta(days=3)
    await session.commit()
    replacement = await owner.post(f"/api/claims/{approved['id']}/pickup-code")
    assert replacement.status_code == 200
    response = await client.post(
        "/api/device/codes/validate",
        headers=headers,
        json={"device_id": "locker_01", "code": replacement.json()["pickup_code"]},
    )
    assert response.json() == {"authorized": True, "compartment": 1, "action": "pickup"}
    result = await admin.put(
        f"/api/admin/items/{item_id}/attributes", json={"category": "phone", "attributes": []}
    )
    assert result.status_code == 200
    assert await session.get(FoundItem, item_id) is not None
