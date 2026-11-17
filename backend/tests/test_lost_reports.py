REPORT = {
    "category": "phone",
    "location": "library",
    "lost_at": "2026-10-14T09:00:00Z",
    "color": "black",
    "brand": "Samsung",
    "description": "Black Samsung phone with a cat sticker",
}


async def test_create_list_get(owner):
    r = await owner.post("/api/lost-reports", json=REPORT)
    assert r.status_code == 201
    report = r.json()
    assert report["status"] == "open" and report["lost_at"] == "2026-10-14T09:00:00"

    assert [x["id"] for x in (await owner.get("/api/lost-reports")).json()] == [report["id"]]
    assert (await owner.get(f"/api/lost-reports/{report['id']}")).status_code == 200


async def test_reports_are_private(owner, other_owner, client):
    report_id = (await owner.post("/api/lost-reports", json=REPORT)).json()["id"]
    assert (await other_owner.get(f"/api/lost-reports/{report_id}")).status_code == 404
    assert (await other_owner.get("/api/lost-reports")).json() == []
    assert (await client.post("/api/lost-reports", json=REPORT)).status_code == 401


async def test_validation(owner):
    r = await owner.post("/api/lost-reports", json={**REPORT, "category": "spaceship"})
    assert r.status_code == 422
    r = await owner.post("/api/lost-reports", json={**REPORT, "location": "mars"})
    assert r.json()["error"]["code"] == "invalid_location"


async def test_report_can_start_with_description_only(owner):
    r = await owner.post("/api/lost-reports", json={"description": "Red fox charm on keyring"})
    assert r.status_code == 201
    assert r.json()["lost_at"] is None
    assert r.json()["location"] == r.json()["category"] == "other"


async def test_report_accepts_category_alias_and_preserves_utc_instant(owner):
    r = await owner.post(
        "/api/lost-reports",
        json={
            **REPORT,
            "category": "Smartphone",
            "lost_at": "2026-10-15T08:00:00+09:00",
            "material": "glass",
            "unique_marks": "Small chip by the camera",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["category"] == "phone"
    assert r.json()["lost_at"] == "2026-10-14T23:00:00"
    assert r.json()["unique_marks"] == "Small chip by the camera"
