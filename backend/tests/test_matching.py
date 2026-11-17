from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.modules.found_items.models import FoundItem, ItemAttribute
from app.modules.matching import policy
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import set_ai_provider
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


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("iPhone", "Apple"),
        ("AirPods", "apple"),
        ("The North Face", "North Face"),
        ("Ray-Ban Inc.", "RayBan Co."),
    ],
)
def test_brand_aliases(left, right):
    assert policy.same_brand(left, right)


def test_ranking_tolerates_missing_attributes_and_prefers_specific_agreement():
    lost, exact = facts(lost_model="iPhone 13", found_model="iPhone 13")
    _, common = facts(found_model=None)
    _, conflict = facts(found_model="iPhone 12")
    ranks = [policy.score(lost, item, 0.7)["total"] for item in (exact, common, conflict)]
    assert ranks[0] > ranks[1] > ranks[2]


def test_common_color_contributes_less_than_rare_color():
    lost, found = facts()
    assert policy.attribute_score(lost, found, 0.9) < policy.attribute_score(lost, found, 0.1)


def test_guessed_category_has_less_influence_than_an_observation():
    lost, found = facts(found_category="umbrella")
    comparison = policy.score(lost, found, None)
    found.reliability = {"category": 0.4}
    assert policy.score(lost, found, None)["total"] > comparison["total"]


def test_different_iphone_model_is_penalized_but_can_still_rank():
    overrides = {"lost_brand": "iPhone", "found_brand": "Apple", "lost_model": "iPhone 12"}
    exact = policy.score(*facts(**overrides, found_model="iPhone 12"), semantic=0.9)
    different = policy.score(*facts(**overrides, found_model="iPhone 13"), semantic=0.9)
    assert 60 <= different["total"] < exact["total"]
    assert policy.plausible(*facts(**overrides, found_model="iPhone 13"), semantic=0.9)


def test_time_score():
    assert 0 < policy.time_score(*facts(found_found_at=T0 - timedelta(days=2))) < 0.5
    assert policy.time_score(*facts(found_found_at=T0 + timedelta(days=2))) == 1
    assert policy.time_score(*facts(found_found_at=T0 + timedelta(days=20))) < 0.5
    assert policy.time_score(*facts(lost_lost_at=None)) == 0.5


def test_attribute_score_neutral_without_data():
    assert policy.attribute_score(*facts(lost_color=None, lost_brand=None)) == 0.5


def test_retrieval_requires_corroboration_before_excluding_a_mismatch():
    lost, item = facts(found_category="umbrella", found_color=None, found_brand=None)
    assert not policy.plausible(lost, item, semantic=0.1)
    assert policy.plausible(lost, item, semantic=None)
    item.reliability = {"category": 0.4}
    assert policy.plausible(lost, item, semantic=0.1)


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
    assert cands[0]["found_item_id"] == match_id
    assert set(cands[0]) == {"found_item_id", "category", "color", "location", "found_date"}

    assert (await other_owner.get(f"/api/lost-reports/{report_id}/candidates")).status_code == 404


async def test_wrong_category_does_not_exclude_strong_match(client, owner, locker, session):
    item_id = await deposit_and_store(client, locker[1])
    item = await session.get(FoundItem, item_id)
    item.category = "wallet"
    item.public_summary = "Secret cat sticker and serial 4821"
    await session.commit()
    report_id = (await owner.post("/api/lost-reports", json=report())).json()["id"]
    result = await owner.get(f"/api/lost-reports/{report_id}/candidates")
    assert result.json()[0]["found_item_id"] == item_id
    assert "4821" not in result.text and "cat sticker" not in result.text


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
    candidates = await owner.get(
        f"/api/lost-reports/{response.json()['id']}/candidates?refresh=false"
    )
    assert [c["found_item_id"] for c in candidates.json()] == [item_id]


async def test_five_casio_candidates_rank_by_description_and_paginate(owner, session):
    descriptions = {
        "blue triangle sticker": 0.75,
        "white paint on strap": 0.45,
        "scratch beside the date": 1.0,
        "scratch under the case": 0.9,
        "no distinctive damage": 0.55,
        "black paint under strap": 0.35,
    }
    found_at = utcnow()
    items = [
        FoundItem(
            category="jewelry",
            location="library",
            status="open",
            found_at=found_at,
            description=description,
            attributes=[
                ItemAttribute(name=name, value=value, visibility="public")
                for name, value in {"brand": "Casio", "color": "black", "model": "F-91W"}.items()
            ],
        )
        for description in descriptions
    ]
    session.add_all(items)
    await session.commit()

    ai = MockAIProvider()
    ai.compare_texts = AsyncMock(
        side_effect=lambda query, candidates: [descriptions[text] for text in candidates]
    )
    set_ai_provider(ai)
    response = await owner.post(
        "/api/lost-reports",
        json=report(
            category="jewelry",
            brand="Casio",
            model="F-91W",
            description="Kratzer neben dem Datum",
        ),
    )
    candidates = await owner.get(
        f"/api/lost-reports/{response.json()['id']}/candidates?refresh=false"
    )
    assert candidates.status_code == 200
    assert [c["found_item_id"] for c in candidates.json()] == [items[i].id for i in (2, 3, 0, 4, 1)]
    page = await owner.get(
        f"/api/lost-reports/{response.json()['id']}/candidates?refresh=false&offset=5"
    )
    assert [c["found_item_id"] for c in page.json()] == [items[5].id]
    assert ai.compare_texts.await_count == 1
    assert set(ai.compare_texts.call_args.args[1]) == descriptions.keys()


async def test_existing_report_gets_matches_when_locker_confirms_deposit(client, owner, locker):
    response = await owner.post("/api/lost-reports", json=report())
    url = f"/api/lost-reports/{response.json()['id']}/candidates?refresh=false"
    assert (await owner.get(url)).json() == []
    item_id = await deposit_and_store(client, locker[1])
    assert [item["found_item_id"] for item in (await owner.get(url)).json()] == [item_id]
