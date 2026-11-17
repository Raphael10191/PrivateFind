from datetime import timedelta
from unittest.mock import AsyncMock

from app.core.db import utcnow
from app.modules.found_items.models import DepositSession, FoundItem
from app.shared import storage
from app.shared.ai.mock import MockAIProvider
from app.shared.ai.provider import AIError, set_ai_provider
from app.shared.ai.schemas import Extraction
from tests.conftest import jpeg


async def start_capture(client):
    return await client.post(
        "/api/deposit-drafts",
        data={"locker_code": "L1", "location": "library"},
        files=[("photos", ("front.jpg", jpeg(), "image/jpeg"))],
    )


def open_draft(response):
    assert response.status_code == 201, response.text
    body = response.json()
    assert "deposit_code" not in body
    return f"/api/deposit-drafts/{body['item_id']}", {"X-Deposit-Token": body["token"]}


async def test_photo_review_precedes_reservation_and_protects_private_details(client, locker):
    ai = MockAIProvider()
    ai.extract_attributes = AsyncMock(
        return_value=Extraction(
            category="phone",
            color="purple",
            material="glass",
            description="Purple phone, a chip beside the rear camera",
            public_summary="Secret damage by camera",
            observations={"category": "estimated", "color": "observed", "material": "unreadable"},
            confidence=0.8,
        )
    )
    set_ai_provider(ai)
    url, headers = open_draft(await start_capture(client))
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2
    assert (await client.get(url, headers={"X-Deposit-Token": "z" * 40})).status_code == 404
    review = (await client.get(url, headers=headers)).json()
    assert review == {
        "status": "done",
        "category": "phone",
        "category_state": "estimated",
        "suggest_photo": True,
    }
    confirmed = await client.post(url + "/confirm", headers=headers, json={"category": "tablet"})
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["deposit_code"]
    assert (await client.post(url + "/confirm", headers=headers, json={})).status_code == 404
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 1


async def test_provider_failure_can_be_retried_or_manually_corrected(client, locker, admin):
    ai = MockAIProvider()
    ai.extract_attributes = AsyncMock(side_effect=AIError("Disconnected"))
    set_ai_provider(ai)
    url, headers = open_draft(await start_capture(client))
    failed = (await client.get(url, headers=headers)).json()
    assert failed["status"] == "failed" and failed["category"] is None
    assert (await client.post(url + "/retry", headers=headers)).status_code == 204
    assert ai.extract_attributes.await_count == 6
    result = await client.post(url + "/confirm", headers=headers, json={"category": "keys"})
    assert result.status_code == 201, result.text
    stored = (await admin.get(f"/api/admin/items/{result.json()['item_id']}")).json()
    assert stored["ai_status"] == "failed" and stored["category"] == "keys"


async def test_editing_photos_discards_old_draft_and_file(client, locker, session):
    capture = await start_capture(client)
    url, headers = open_draft(capture)
    item = await session.get(FoundItem, capture.json()["item_id"])
    path = storage.photo_path(item.photos[0].file_name)
    assert path.exists()
    assert (await client.post(url + "/discard", headers=headers)).status_code == 204
    assert not path.exists()
    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.get("/api/lockers/L1")).json()["free_compartments"] == 2


async def test_expired_draft_cannot_be_confirmed(client, locker, session):
    capture = await start_capture(client)
    url, headers = open_draft(capture)
    item = await session.get(FoundItem, capture.json()["item_id"])
    draft = await session.get(DepositSession, item.session_id)
    draft.expires_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    assert (await client.post(url + "/confirm", headers=headers, json={})).status_code == 404
    new = await start_capture(client)
    assert new.status_code == 201, new.text
    assert await session.get(FoundItem, new.json()["item_id"]) is not None
