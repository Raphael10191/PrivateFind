from datetime import timedelta

from sqlalchemy import select

from app.modules.found_items import service
from app.modules.found_items.models import FoundItem
from app.modules.locker.models import AccessCode
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import set_ai_provider
from tests.conftest import deposit, deposit_and_store


async def item(session, item_id) -> FoundItem:
    session.expire_all()
    return await session.get(FoundItem, item_id)


async def test_deposit_returns_code_and_runs_ai(client, session, locker):
    r = await deposit(client)
    assert r.status_code == 201
    body = r.json()
    assert body["compartment"] == 1 and len(body["deposit_code"]) == 6

    it = await item(session, body["item_id"])
    assert it.status == "awaiting_deposit"
    assert it.ai_status == "done"  # background task ran after the response
    assert it.category == "phone"
    assert it.attr("color") == "black"
    assert {a.name for a in it.private_attributes()} == {"serial_suffix", "sticker_or_mark"}


async def test_full_flow_to_stored(client, session, locker):
    _, h = locker
    item_id = await deposit_and_store(client, h)
    assert (await item(session, item_id)).status == "open"
    r = await client.get("/api/lockers/L1")
    assert r.json()["free_compartments"] == 1


async def test_empty_after_open_cancels_deposit(client, session, locker):
    _, h = locker
    body = (await deposit(client)).json()
    await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": body["deposit_code"]},
        headers=h,
    )
    r = await client.post(
        "/api/device/compartments/1/state",
        json={"device_id": "locker_01", "occupied": False},
        headers=h,
    )
    assert r.json()["state"] == "free"
    assert (await item(session, body["item_id"])).status == "expired"


async def test_expired_deposit_code_frees_compartment(client, session, locker):
    body = (await deposit(client)).json()
    code = await session.scalar(select(AccessCode))
    code.expires_at -= timedelta(hours=1)
    await session.commit()

    r = await client.get("/api/lockers/L1")
    assert r.json()["free_compartments"] == 2
    assert (await item(session, body["item_id"])).status == "expired"


async def test_locker_full(client, locker):
    await deposit(client)
    await deposit(client)
    r = await deposit(client)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "compartment_unavailable"


async def test_bad_inputs(client, locker):
    assert (await deposit(client, n_photos=4)).status_code == 422
    assert (await deposit(client, location="mars")).json()["error"]["code"] == "invalid_location"
    r = await client.post(
        "/api/deposits",
        data={"locker_code": "L1", "location": "library", "note": "x"},
        files=[("photos", ("a.gif", b"GIF89a", "image/gif"))],
    )
    assert r.json()["error"]["code"] == "invalid_photo"


async def test_deposit_rate_limit(client, session, locker):
    for _ in range(5):
        await deposit(client, location="mars")  # rejected by the service, still counted
    r = await deposit(client)
    assert r.status_code == 429


class FlakyAI(MockAIProvider):
    def __init__(self, failures):
        self.failures = failures

    async def extract_attributes(self, photos, note):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("AI unavailable")
        return await super().extract_attributes(photos, note)


async def test_ai_retry_then_success(client, session, locker):
    set_ai_provider(FlakyAI(failures=2))
    body = (await deposit(client)).json()
    it = await item(session, body["item_id"])
    assert (it.ai_status, it.ai_attempts) == ("done", 3)


async def test_ai_failure_then_admin_retry(client, admin, session, locker):
    set_ai_provider(FlakyAI(failures=3))
    body = (await deposit(client)).json()
    it = await item(session, body["item_id"])
    assert it.ai_status == "failed" and it.ai_error == "AI unavailable"

    r = await admin.get("/api/admin/items", params={"ai_status": "failed"})
    assert [i["id"] for i in r.json()] == [body["item_id"]]

    r = await admin.post(f"/api/admin/items/{body['item_id']}/retry-ai")  # provider works now
    assert r.status_code == 202
    assert (await item(session, body["item_id"])).ai_status == "done"


async def test_requeue_pending_on_startup(session, locker):
    lk, _ = locker
    session.add(FoundItem(locker_id=lk.id, location="library", note="red umbrella"))
    await session.commit()
    assert await service.requeue_pending() == 1
    await next(iter(service._tasks))  # wait for the scheduled task
    it = await item(session, 1)
    assert it.ai_status == "done" and it.category == "umbrella"


async def test_admin_item_detail_and_correction(client, admin, owner, session, locker):
    item_id = (await deposit(client)).json()["item_id"]

    assert (await owner.get(f"/api/admin/items/{item_id}")).status_code == 403

    data = (await admin.get(f"/api/admin/items/{item_id}")).json()
    assert data["compartment"] == 1 and len(data["photo_ids"]) == 1

    r = await admin.get(f"/api/admin/items/{item_id}/photos/{data['photo_ids'][0]}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"

    r = await admin.put(
        f"/api/admin/items/{item_id}/attributes",
        json={
            "category": "phone",
            "attributes": [
                {"name": "color", "value": "blue", "visibility": "public"},
                {
                    "name": "serial_suffix",
                    "value": "1111",
                    "visibility": "private",
                    "strength": "strong",
                },
            ],
        },
    )
    assert r.status_code == 200
    assert {a["value"] for a in r.json()["attributes"]} == {"blue", "1111"}


async def test_each_deposit_gets_its_own_compartment(client, session, locker):
    await deposit(client)
    await deposit(client)
    assert sorted(
        await session.scalars(select(FoundItem.id).where(FoundItem.compartment_id.is_not(None)))
    ) == [1, 2]
