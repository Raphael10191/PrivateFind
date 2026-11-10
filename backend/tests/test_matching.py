from datetime import datetime, timedelta

from app.core.db import utcnow
from app.modules.matching import policy
from tests.conftest import deposit_and_store

T0 = datetime(2026, 10, 14, 9, 0)


def facts(**kw):
    lost = dict(category="phone", location="library", lost_at=T0, color="black", brand="Samsung")
    found = dict(
        category="phone",
        location="library",
        found_at=T0 + timedelta(hours=3),
        color="black",
        brand="samsung",
    )
    lost.update({k[5:]: v for k, v in kw.items() if k.startswith("lost_")})
    found.update({k[6:]: v for k, v in kw.items() if k.startswith("found_")})
    return policy.LostFacts(**lost), policy.FoundFacts(**found)


def test_perfect_match_scores_100():
    assert policy.score(*facts(), semantic=1.0)["total"] == 100


def test_component_scores():
    lost, found = facts(found_location="gym", found_color="blue")
    points = policy.score(lost, found, semantic=0.5)
    assert points["location"] == 0 and points["attributes"] == 12.5 and points["semantic"] == 10
    assert points["total"] == 62  # 25 + 0 + 15 + 12.5 + 10 = 62.5, rounded half to even


def test_time_score():
    assert policy.time_score(*facts(found_found_at=T0 - timedelta(days=2))) == 0.0
    assert policy.time_score(*facts(found_found_at=T0 + timedelta(days=2))) == 0.6
    assert policy.time_score(*facts(found_found_at=T0 + timedelta(days=20))) == 0.1


def test_attribute_score_neutral_without_data():
    assert policy.attribute_score(*facts(lost_color=None, lost_brand=None)) == 0.5


def test_top_candidates_threshold_and_limit():
    scored = [(i, {"total": t}) for i, t in enumerate([90, 59, 60, 75, 99])]
    assert [i for i, _ in policy.top_candidates(scored, 60, 3)] == [4, 0, 3]


def report(**kw):
    lost_at = (utcnow() - timedelta(hours=2)).isoformat()
    return {
        "category": "phone",
        "location": "library",
        "lost_at": lost_at,
        "color": "black",
        "brand": "Samsung",
        "description": "Black Samsung phone with a cat sticker",
        **kw,
    }


async def test_candidates_endpoint(client, owner, other_owner, locker):
    _, h = locker
    match_id = await deposit_and_store(client, h)
    await deposit_and_store(client, h, note="Silver Apple phone near the gym", location="gym")

    report_id = (await owner.post("/api/lost-reports", json=report())).json()["id"]
    r = await owner.get(f"/api/lost-reports/{report_id}/candidates")
    assert r.status_code == 200
    cands = r.json()
    assert [c["found_item_id"] for c in cands] == [match_id]  # weak phone is below 60
    c = cands[0]
    assert c["score"] == 100 and c["breakdown"]["category"] == 25
    assert set(c) == {
        "found_item_id",
        "score",
        "breakdown",
        "category",
        "color",
        "location",
        "found_date",
        "public_summary",
    }  # nothing private

    assert (await other_owner.get(f"/api/lost-reports/{report_id}/candidates")).status_code == 404


async def test_only_stored_items_of_same_category(client, owner, locker):
    _, h = locker
    await deposit_and_store(client, h, note="Black umbrella")
    report_id = (await owner.post("/api/lost-reports", json=report())).json()["id"]
    assert (await owner.get(f"/api/lost-reports/{report_id}/candidates")).json() == []
