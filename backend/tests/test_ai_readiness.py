from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.shared.ai import readiness
from app.shared.ai.provider import AIError
from tests.test_capture_workflow import start_capture
from tests.test_matching import report


async def test_mock_blocks_ai_submissions_but_keeps_health_and_read_access(
    app, client, owner, locker
):
    app.dependency_overrides.pop(readiness.require_ai_ready)
    assert (await client.get("/api/ai/status")).json() == {"provider": "mock", "available": False}
    assert (await client.get("/api/health")).status_code == 200
    assert (await owner.get("/api/lost-reports")).json() == []

    responses = (
        await start_capture(client),
        await owner.post("/api/lost-reports", json=report()),
        await owner.post("/api/claims", json={"lost_report_id": 1, "found_item_id": 1}),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ai_unavailable"
    assert (await owner.get("/api/lost-reports")).json() == []


async def test_live_readiness_checks_vision_and_recovers(app, client, owner, monkeypatch):
    app.dependency_overrides.pop(readiness.require_ai_ready)
    now = [0]
    vision = AsyncMock(side_effect=[AIError("Tunnel down"), []])
    monkeypatch.setattr(readiness, "_last_check", None)
    monkeypatch.setattr(readiness, "monotonic", lambda: now[0])
    monkeypatch.setattr(readiness, "get_settings", lambda: SimpleNamespace(ai_provider="qwen"))
    monkeypatch.setattr(readiness, "get_ai_provider", lambda: SimpleNamespace(verify_photos=vision))

    assert (await client.get("/api/ai/status")).json() == {"provider": "qwen", "available": False}
    assert (await owner.post("/api/lost-reports", json=report())).status_code == 503
    assert vision.await_count == 1

    now[0] += 6
    assert (await client.get("/api/ai/status")).json() == {"provider": "qwen", "available": True}
    assert (await owner.post("/api/lost-reports", json=report())).status_code == 201
    assert vision.await_count == 2
