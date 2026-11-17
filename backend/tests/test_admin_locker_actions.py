from app.modules.locker import service
from tests.conftest import deposit, jpeg
from tests.test_claims import GOOD, claim, setup_candidate


async def validate(client, headers, code, device_id="locker_01"):
    response = await client.post(
        "/api/device/codes/validate", headers=headers, json={"device_id": device_id, "code": code}
    )
    assert response.status_code == 200
    return response.json()["authorized"]


async def test_remove_item_revokes_deposit_code_and_is_safe_to_repeat(client, owner, admin, locker):
    _, headers = locker
    data = (await deposit(client)).json()
    url = f"/api/admin/items/{data['item_id']}/remove"
    assert (await client.post(url)).status_code == 401
    assert (await owner.post(url)).status_code == 403
    assert (await admin.post("/api/admin/items/999/remove")).status_code == 404

    assert (await admin.post(url)).json() == {"ok": True}
    item = await admin.get(f"/api/admin/items/{data['item_id']}")
    assert item.json()["status"] == "expired"
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2
    assert not await validate(client, headers, data["deposit_code"])

    new = (await deposit(client)).json()
    assert new["compartment"] == data["compartment"]
    assert (await admin.post(url)).status_code == 200
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 1
    assert await validate(client, headers, new["deposit_code"])


async def test_remove_item_revokes_pickup_code(client, owner, admin, locker):
    item_id, report_id, headers = await setup_candidate(client, owner, locker)
    approved = (await claim(owner, report_id, item_id, GOOD)).json()
    assert approved["status"] == "approved"
    assert (await admin.post(f"/api/admin/items/{item_id}/remove")).status_code == 200
    assert not await validate(client, headers, approved["pickup_code"])
    assert (await owner.post(f"/api/claims/{approved['id']}/pickup-code")).status_code == 409

    entries = (await admin.get("/api/admin/audit")).json()
    removed = next(entry for entry in entries if entry["action"] == "admin_item_removed")
    assert removed["entity_id"] == item_id and removed["actor_type"] == "admin"


async def test_reset_locker_expires_all_active_items_only_in_selected_locker(
    client,
    owner,
    admin,
    locker,
    session,
):
    item_id, report_id, headers = await setup_candidate(client, owner, locker)
    pickup = (await claim(owner, report_id, item_id, GOOD)).json()
    pending = (await deposit(client)).json()

    _, key = await service.create_locker(session, "L2", "Other locker", "gym", 1, "locker_02")
    other = (
        await client.post(
            "/api/deposits",
            data={"locker_code": "L2", "location": "gym", "note": "blue umbrella"},
            files=[("photos", ("photo.jpg", jpeg(), "image/jpeg"))],
        )
    ).json()

    url = "/api/admin/lockers/L1/reset"
    assert (await owner.post(url)).status_code == 403
    assert (await admin.post("/api/admin/lockers/unknown/reset")).status_code == 404
    assert (await admin.post(url)).json() == {"ok": True}
    for expired_id in (item_id, pending["item_id"]):
        assert (await admin.get(f"/api/admin/items/{expired_id}")).json()["status"] == "expired"
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2
    assert not await validate(client, headers, pickup["pickup_code"])
    assert not await validate(client, headers, pending["deposit_code"])
    assert (await client.get("/api/lockers/L2")).json()["free_compartments"] == 0
    assert await validate(client, {"X-Device-Key": key}, other["deposit_code"], "locker_02")

    entries = (await admin.get("/api/admin/audit")).json()
    reset = next(entry for entry in entries if entry["action"] == "admin_locker_reset")
    assert reset["actor_type"] == "admin"
