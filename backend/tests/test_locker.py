from app.modules.found_items.models import FoundItem
from app.modules.locker import policy, service


async def make_locker(session, compartments=2):
    return await service.create_locker(session, "L1", "Library locker", "library", compartments)


def test_policy_transitions():
    assert policy.next_state_on_code("deposit_reserved", "deposit") == "deposit_open"
    assert policy.next_state_on_code("occupied", "deposit") is None
    assert policy.next_state_on_report("deposit_open", True) == ("occupied", "deposited")
    assert policy.next_state_on_report("free", True) is None
    assert all(len(m) <= 16 for m in policy.MESSAGES.values())


async def test_locker_info(client, session):
    await make_locker(session)
    r = await client.get("/api/lockers/L1")
    assert r.status_code == 200
    assert r.json()["free_compartments"] == 2
    assert (await client.get("/api/lockers/NOPE")).status_code == 404


async def test_device_requires_key(client, session):
    await make_locker(session)
    r = await client.post(
        "/api/device/codes/validate", json={"device_id": "locker_01", "code": "123456"}
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": "123456"},
        headers={"X-Device-Key": "wrong"},
    )
    assert r.status_code == 401


async def test_deposit_code_opens_once(client, session):
    locker, key = await make_locker(session)
    session.add(FoundItem(locker_id=locker.id, location="library", note="phone"))
    await session.flush()
    issued = await service.reserve_for_deposit(session, locker, item_id=1)
    await session.commit()
    h = {"X-Device-Key": key}

    r = await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": issued.code},
        headers=h,
    )
    assert r.json() == {"authorized": True, "compartment": 1, "action": "deposit"}
    r = await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": issued.code},
        headers=h,
    )
    assert r.json()["authorized"] is False  # single use


async def test_full_locker_and_wrong_code_limit(client, session):
    locker, key = await make_locker(session, compartments=1)
    session.add(FoundItem(locker_id=locker.id, location="library", note="phone"))
    await session.flush()
    await service.reserve_for_deposit(session, locker, item_id=1)
    await session.commit()
    try:
        await service.reserve_for_deposit(session, locker, item_id=2)
        raise AssertionError("expected compartment_unavailable")
    except Exception as exc:
        assert getattr(exc, "code", None) == "compartment_unavailable"

    h = {"X-Device-Key": key}
    for _ in range(5):
        r = await client.post(
            "/api/device/codes/validate",
            json={"device_id": "locker_01", "code": "000000"},
            headers=h,
        )
        assert r.json()["authorized"] is False
    r = await client.post(
        "/api/device/codes/validate", json={"device_id": "locker_01", "code": "000000"}, headers=h
    )
    assert r.json()["authorized"] is False
