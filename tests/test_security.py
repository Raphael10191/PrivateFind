"""Security tests (work packages 8.2 and 8.3, Week 10 security audit)."""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from backend import config
from backend.database.models import AuditLog, Claim, ClaimStatus, FoundItem, LostReport, User
from backend.database.seed import seed_demo
from backend.services import attempts, matching
from tests.conftest import DEVICE
from tests.test_flow import PHOTOS, deposit

NOW = datetime.now()
REPORT = {
    "category": "wallet",
    "location": "Library",
    "lost_from": (NOW - timedelta(hours=2)).isoformat(),
    "lost_to": NOW.isoformat(),
}


def test_fake_photo_is_rejected(client):
    token = client.post("/api/deposit-sessions", json={"locker_id": 1}).json()["token"]
    # The browser says "image/jpeg", but the file is a text file
    fake = [("photos", (f"p{i}.jpg", b"<script>alert(1)</script>", "image/jpeg")) for i in range(3)]
    response = client.post("/api/deposits", data={"token": token, "location": "Library"}, files=fake)
    assert response.status_code == 400
    assert "not a real photo" in response.json()["detail"]


def test_unknown_category_is_rejected(client, owner_headers):
    token = client.post("/api/deposit-sessions", json={"locker_id": 1}).json()["token"]
    response = client.post(
        "/api/deposits", data={"token": token, "location": "Library", "category": "rocket"}, files=PHOTOS
    )
    assert response.status_code == 400

    response = client.post("/api/lost-reports", headers=owner_headers, json={**REPORT, "category": "rocket"})
    assert response.status_code == 400


def test_sql_injection_is_stored_as_normal_text(client, db_factory, owner_headers):
    """SQLAlchemy sends values as parameters, never as part of the SQL command."""
    evil = "Library'; DROP TABLE found_item; --"
    response = client.post("/api/lost-reports", headers=owner_headers, json={**REPORT, "location": evil})
    assert response.status_code == 201
    with db_factory() as db:
        assert db.scalar(select(LostReport)).location == evil
        assert db.scalar(select(FoundItem)) is None  # the table still exists, the query works


def test_rate_limit_per_ip(client, owner_headers):
    for _ in range(config.RATE_LIMIT_PER_MINUTE):
        assert client.get("/api/lost-reports", headers=owner_headers).status_code == 200
    assert client.get("/api/lost-reports", headers=owner_headers).status_code == 429


def test_audit_log_only_for_admin(client, owner_headers, admin_headers):
    deposit(client)
    assert client.get("/api/admin/audit-log").status_code == 401
    assert client.get("/api/admin/audit-log", headers=owner_headers).status_code == 403

    log = client.get("/api/admin/audit-log", headers=admin_headers).json()
    actions = [entry["action"] for entry in log]
    assert "item_deposited" in actions
    # the plain deposit code is never in the log
    assert all("code" not in json.dumps(entry["details"] or {}) for entry in log)


def test_many_wrong_codes_create_an_alert(client, admin_headers):
    body = {"device_id": "locker_01", "code": "000000"}
    for _ in range(config.ALERT_WRONG_CODES_PER_LOCKER):
        assert client.post("/api/device/codes/validate", json=body, headers=DEVICE).json()["authorized"] is False

    alerts = client.get("/api/admin/audit-log?only_alerts=true", headers=admin_headers).json()
    assert [a["action"] for a in alerts] == ["alert_many_wrong_codes"]


def test_many_failed_claims_create_an_alert(db):
    seed_demo(db)
    report = db.scalar(select(LostReport))
    match = matching.update_candidates(db, report)[0]
    other = db.scalar(select(User).where(User.username == "admin"))

    for _ in range(config.ALERT_FAILED_CLAIMS_PER_ITEM):
        db.add(Claim(match_candidate=match, user=other, status=ClaimStatus.REJECTED))
        attempts.alert_if_many_failed_claims(db, match.item_id)
    db.flush()

    alerts = db.scalars(select(AuditLog).where(AuditLog.action == "alert_many_failed_claims")).all()
    assert len(alerts) == 1
    assert alerts[0].entity_id == match.item_id
