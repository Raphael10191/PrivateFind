"""End-to-end flow through the API: deposit -> locker -> lost report -> candidates -> pickup."""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from backend import config
from backend.database.models import (
    Claim,
    ClaimStatus,
    Compartment,
    CompartmentState,
    FoundItem,
    FoundItemStatus,
    LostReport,
    LostReportStatus,
    MatchCandidate,
    User,
)
from backend.services import locker as locker_service
from tests.conftest import DEVICE

# A JPEG file starts with the bytes FF D8 FF
PHOTOS = [("photos", (f"p{i}.jpg", b"\xff\xd8\xff test photo", "image/jpeg")) for i in range(3)]


def deposit(client, category="wallet", location="Gwanggaeto Hall, 3rd floor"):
    token = client.post("/api/deposit-sessions", json={"locker_id": 1}).json()["token"]
    answers = [{"name": "contents", "value": "student card", "weight": 3}]
    response = client.post(
        "/api/deposits",
        data={"token": token, "location": location, "category": category, "answers": json.dumps(answers)},
        files=PHOTOS,
    )
    assert response.status_code == 201, response.text
    return token, response.json()


def test_full_flow(client, db_factory, owner_headers):
    # 1-2: finder deposits an item
    token, dep = deposit(client)
    assert dep["compartment"] == 1
    assert len(dep["deposit_code"]) == config.CODE_LENGTH

    # the session can only be used once
    again = client.post("/api/deposits", data={"token": token, "location": "x"}, files=PHOTOS)
    assert again.status_code == 400

    # photos are stored in the private upload folder
    with db_factory() as db:
        item = db.get(FoundItem, dep["item_id"])
        assert item.status == FoundItemStatus.AWAITING_DEPOSIT
        assert len(item.photos) == 3
        for photo in item.photos:
            assert (config.UPLOAD_DIR / photo.storage_path).exists()

    # 3: locker checks the code
    body = {"device_id": "locker_01", "code": dep["deposit_code"]}
    assert client.post("/api/device/codes/validate", json=body).status_code == 401  # no key
    wrong = client.post("/api/device/codes/validate", json={**body, "code": "000000"}, headers=DEVICE)
    assert wrong.json()["authorized"] is False
    ok = client.post("/api/device/codes/validate", json=body, headers=DEVICE)
    assert ok.json() == {"authorized": True, "compartment": 1, "action": "deposit"}
    assert '"authorized":true' in ok.text  # the firmware searches for this text
    reused = client.post("/api/device/codes/validate", json=body, headers=DEVICE)
    assert reused.json()["authorized"] is False  # one-time code

    # door closed, IR sensor sees the item
    state = client.post("/api/device/compartments/1/state",
                        json={"device_id": "locker_01", "occupied": True}, headers=DEVICE)
    assert state.json()["state"] == "occupied"

    # 4: owner reports the lost item and sees the candidate
    now = datetime.now()
    report = client.post("/api/lost-reports", headers=owner_headers, json={
        "category": "wallet", "location": "Gwanggaeto Hall, 3rd floor",
        "lost_from": (now - timedelta(hours=3)).isoformat(),
        "lost_to": now.isoformat(),
        "description": "black wallet",
    })
    assert report.status_code == 201, report.text
    report_id = report.json()["report_id"]

    cands = client.get(f"/api/lost-reports/{report_id}/candidates", headers=owner_headers).json()
    assert [c["item_id"] for c in cands] == [dep["item_id"]]
    assert cands[0]["match_score"] >= 60
    assert "student card" not in json.dumps(cands)  # private answer is never shown
    assert client.get(f"/api/lost-reports/{report_id}/candidates").status_code == 401

    # 5-6: claim approved (done by 9.1 later) -> pickup code -> locker opens -> item taken
    with db_factory() as db:
        owner = db.scalar(select(User).where(User.username == "testowner"))
        match = db.scalar(select(MatchCandidate).where(MatchCandidate.item_id == dep["item_id"]))
        claim = Claim(match_candidate=match, user=owner, status=ClaimStatus.APPROVED, ownership_score=90)
        db.add(claim)
        db.flush()
        pickup_code = locker_service.create_pickup_code(db, claim)
        db.commit()

    ok = client.post("/api/device/codes/validate",
                     json={"device_id": "locker_01", "code": pickup_code}, headers=DEVICE)
    assert ok.json() == {"authorized": True, "compartment": 1, "action": "pickup"}
    state = client.post("/api/device/compartments/1/state",
                        json={"device_id": "locker_01", "occupied": False}, headers=DEVICE)
    assert state.json()["state"] == "free"

    with db_factory() as db:
        assert db.get(FoundItem, dep["item_id"]).status == FoundItemStatus.RETURNED
        assert db.get(LostReport, report_id).status == LostReportStatus.RESOLVED


def test_no_free_compartment(client):
    deposit(client)  # our locker has only one compartment
    full = client.post("/api/deposit-sessions", json={"locker_id": 1})
    assert full.status_code == 409


def test_expired_deposit_code_frees_compartment(client, db_factory):
    _, dep = deposit(client)
    with db_factory() as db:
        for code in db.get(FoundItem, dep["item_id"]).compartment.access_codes:
            code.expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()
    _, dep2 = deposit(client)
    assert dep2["compartment"] == 1  # compartment 1 was released and is used again
    with db_factory() as db:
        assert db.get(FoundItem, dep["item_id"]).status == FoundItemStatus.EXPIRED
        c1 = db.scalar(select(Compartment).where(Compartment.number == 1))
        assert c1.state == CompartmentState.DEPOSIT_RESERVED


def test_deposit_needs_three_photos(client):
    token = client.post("/api/deposit-sessions", json={"locker_id": 1}).json()["token"]
    response = client.post("/api/deposits", data={"token": token, "location": "Library"}, files=PHOTOS[:2])
    assert response.status_code == 400
    assert "3 photos" in response.json()["detail"]
