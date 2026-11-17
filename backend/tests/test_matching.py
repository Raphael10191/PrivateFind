from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.modules.found_items.models import FoundItem
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
    assert points == {
        "category": 15,
        "location": 1.5,
        "time": 10,
        "attributes": 20,
        "semantic": 20,
        "total": 66,
    }


@pytest.mark.parametrize(
    ("overrides", "semantic", "expected"),
    [
        pytest.param(
            {
                "lost_category": "jewelry",
                "found_category": "jewelry",
                "lost_brand": "Rolex",
                "found_brand": "Casio",
            },
            1.0,
            45,
            id="rolex-vs-casio",
        ),
        pytest.param(
            {
                "lost_category": "jewelry",
                "found_category": "jewelry",
                "lost_brand": "Casio",
                "found_brand": "Casio",
                "lost_model": "F-91W",
                "found_model": "F105W",
            },
            0.4,
            59,
            id="different-casio-model-numbers",
        ),
        pytest.param(
            {"lost_brand": "iPhone", "found_brand": "Apple"},
            1.0,
            100,
            id="iphone-brand-alias",
        ),
        pytest.param(
            {"lost_brand": None, "lost_model": "Galaxy S25", "found_brand": "Samsung"},
            1.0,
            100,
            id="infer-brand-from-model",
        ),
        pytest.param(
            {"lost_brand": "The North Face", "found_brand": "North Face"},
            1.0,
            100,
            id="brand-article",
        ),
        pytest.param(
            {"lost_brand": "Ray-Ban", "found_brand": "RayBan"},
            1.0,
            100,
            id="brand-punctuation",
        ),
        pytest.param(
            {
                "lost_brand": "Apple",
                "found_brand": "Apple",
                "lost_model": "iPhone 13",
                "found_model": "iPhone 13 Pro",
            },
            1.0,
            99,
            id="related-iphone-model",
        ),
        pytest.param(
            {"lost_color": "grey", "found_color": "silver"},
            1.0,
            95,
            id="related-shades",
        ),
        pytest.param({"found_color": "white"}, 1.0, 55, id="clear-color-conflict"),
        pytest.param({"found_color": "multicolor"}, 1.0, 94, id="multicolor"),
        pytest.param({"found_category": "other"}, 1.0, 91, id="uncertain-found-category"),
        pytest.param({"lost_category": "other"}, 1.0, 91, id="uncertain-report-category"),
        pytest.param({"found_location": "gym"}, 1.0, 92, id="different-location"),
    ],
)
def test_matching_edge_cases(overrides, semantic, expected):
    assert policy.score(*facts(**overrides), semantic=semantic)["total"] == expected


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
    assert c["score"] == 100 and c["breakdown"]["category"] == 15
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


@pytest.mark.parametrize(
    ("report_category", "item_category"), [("phone", "other"), ("other", "phone")]
)
async def test_candidates_include_category_other(
    client, owner, locker, session, report_category, item_category
):
    _, h = locker
    item_id = await deposit_and_store(client, h)
    item = await session.scalar(select(FoundItem).where(FoundItem.id == item_id))
    item.category = item_category
    await session.commit()

    response = await owner.post("/api/lost-reports", json=report(category=report_category))
    candidates = await owner.get(f"/api/lost-reports/{response.json()['id']}/candidates")
    assert [c["found_item_id"] for c in candidates.json()] == [item_id]
    assert candidates.json()[0]["breakdown"]["category"] == 6
