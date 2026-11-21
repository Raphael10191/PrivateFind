from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import db
from app.core.config import MOCK_REPORTING_DATABASE_URL, Settings, get_settings
from app.core.errors import AppError
from app.main import create_app
from app.modules.claims.models import Claim
from app.modules.found_items.models import FoundItem, ItemPhoto
from app.modules.locker.models import AccessCode, Compartment, Locker
from app.shared.ai import readiness
from app.shared.ai.provider import AIError
from tests.test_capture_workflow import start_capture
from tests.test_matching import report


async def test_mock_blocks_ai_submissions_but_keeps_health_and_read_access(
    app, client, owner, locker
):
    app.dependency_overrides.pop(readiness.require_ai_ready)
    app.dependency_overrides.pop(readiness.require_report_ai_ready)
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


@pytest.mark.parametrize("provider", ["qwen", "claude"])
async def test_live_readiness_checks_vision_and_recovers(app, client, owner, monkeypatch, provider):
    app.dependency_overrides.pop(readiness.require_ai_ready)
    app.dependency_overrides.pop(readiness.require_report_ai_ready)
    now = [0]
    vision = AsyncMock(side_effect=[AIError("Tunnel down"), []])
    monkeypatch.setattr(readiness, "_last_check", None)
    monkeypatch.setattr(readiness, "monotonic", lambda: now[0])
    monkeypatch.setattr(readiness, "get_settings", lambda: SimpleNamespace(ai_provider=provider))
    monkeypatch.setattr(readiness, "get_ai_provider", lambda: SimpleNamespace(verify_photos=vision))

    assert (await client.get("/api/ai/status")).json() == {"provider": provider, "available": False}
    assert (await owner.post("/api/lost-reports", json=report())).status_code == 503
    assert vision.await_count == 1

    now[0] += 6
    assert (await client.get("/api/ai/status")).json() == {"provider": provider, "available": True}
    assert (await owner.post("/api/lost-reports", json=report())).status_code == 201
    assert vision.await_count == 2


def test_mock_reporting_defaults_off(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ALLOW_MOCK_AI_REPORTS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "production"
    assert settings.allow_mock_ai_reports is False
    assert settings.mock_reporting_enabled is False


def test_normal_session_cookie_is_unchanged(app):
    assert app.user_middleware[0].kwargs["session_cookie"] == "session"


async def test_development_label_and_client_flags_cannot_enable_reporting(app, owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "development")
    app.dependency_overrides.pop(readiness.require_ai_ready)
    app.dependency_overrides.pop(readiness.require_report_ai_ready)
    response = await owner.post(
        "/api/lost-reports?mock_reporting_enabled=true",
        json={**report(), "mock_reporting_enabled": True},
        headers={"X-Allow-Mock-AI-Reports": "true"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"


@pytest.mark.parametrize(
    ("environment", "provider", "database"),
    [
        ("production", "mock", MOCK_REPORTING_DATABASE_URL),
        ("test", "mock", MOCK_REPORTING_DATABASE_URL),
        ("development", "qwen", MOCK_REPORTING_DATABASE_URL),
        ("development", "claude", MOCK_REPORTING_DATABASE_URL),
        ("development", "mock", "mysql+asyncmy://local:local@localhost/privatefind"),
        ("development", "mock", "sqlite+aiosqlite:///shared.sqlite3"),
    ],
)
def test_mock_reporting_rejects_unsafe_configuration(environment, provider, database):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=environment,
            ai_provider=provider,
            database_url=database,
            allow_mock_ai_reports=True,
        )


@pytest.fixture
def mock_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "allow_mock_ai_reports", True)
    # conftest already uses SQLite memory. Validate the entire opt-in explicitly.
    Settings(_env_file=None, **settings.model_dump())
    assert settings.database_url == MOCK_REPORTING_DATABASE_URL
    return settings


@pytest.fixture
async def mock_app(mock_settings, monkeypatch):
    # Separate engine and empty database, not the normal test/app connection.
    engine = db._make_engine(MOCK_REPORTING_DATABASE_URL)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    application = create_app()
    assert not application.dependency_overrides
    try:
        async with application.router.lifespan_context(application):
            yield application
    finally:
        await engine.dispose()


@pytest.fixture
async def mock_client(mock_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_app), base_url="http://mock.test"
    ) as client:
        yield client


async def register_mock_owner(client, email="local-owner@example.com"):
    response = await client.post(
        "/api/auth/register", json={"email": email, "password": "local-test-password"}
    )
    assert response.status_code == 201, response.text
    assert "privatefind_mock_session=" in response.headers["set-cookie"]


async def test_explicit_mock_reporting_creates_reports_without_real_ai_or_notifications(
    mock_client, monkeypatch
):
    outbound = AsyncMock(side_effect=AssertionError("External HTTP must not be called"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", outbound)
    await register_mock_owner(mock_client)
    assert (await mock_client.get("/api/ai/status")).json() == {
        "provider": "mock", "available": False, "mock_reporting_enabled": True
    }
    response = await mock_client.post("/api/lost-reports", json=report())
    assert response.status_code == 201, response.text
    report_id = response.json()["id"]
    assert (await mock_client.get("/api/lost-reports")).json()[0]["id"] == report_id
    assert (await mock_client.get(f"/api/lost-reports/{report_id}")).status_code == 200
    assert (
        await mock_client.get(f"/api/lost-reports/{report_id}/candidates?refresh=false")
    ).json() == []
    assert (await mock_client.get("/api/claims")).json() == []
    outbound.assert_not_awaited()
    async with db.SessionLocal() as session:
        for model in (Claim, AccessCode, FoundItem, ItemPhoto, Locker, Compartment):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_mock_candidates_use_only_isolated_fixtures_and_remain_private(mock_client):
    from datetime import datetime

    from app.modules.found_items.models import ItemAttribute

    await register_mock_owner(mock_client)
    # Database-only unit fixture: no device command or physical deposit acknowledgement.
    async with db.SessionLocal() as session:
        item = FoundItem(
            category="phone", location="library", status="open", ai_status="done",
            found_at=datetime(2026, 10, 14, 12),
            description="Black Samsung phone with a cat sticker",
        )
        item.attributes = [
            ItemAttribute(name="color", value="black", visibility="public"),
            ItemAttribute(name="engraving", value="private fixture", visibility="private"),
        ]
        session.add(item)
        await session.commit()
        item_id = item.id
    created = await mock_client.post(
        "/api/lost-reports", json=report(lost_at="2026-10-14T09:00:00")
    )
    report_id = created.json()["id"]
    response = await mock_client.get(
        f"/api/lost-reports/{report_id}/candidates?refresh=false"
    )
    assert response.status_code == 200, response.text
    assert [row["found_item_id"] for row in response.json()] == [item_id]
    assert set(response.json()[0]) == {
        "found_item_id", "category", "color", "location", "found_date"
    }
    assert "private fixture" not in response.text


async def test_mock_reporting_keeps_authentication_and_owner_isolation(mock_app, mock_client):
    assert (await mock_client.post("/api/lost-reports", json=report())).status_code == 401
    await register_mock_owner(mock_client)
    created = await mock_client.post("/api/lost-reports", json=report())
    report_id = created.json()["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_app), base_url="http://mock.test"
    ) as other:
        await register_mock_owner(other, "other-local@example.com")
        assert (await other.get(f"/api/lost-reports/{report_id}")).status_code == 404
        assert (
            await other.get(f"/api/lost-reports/{report_id}/candidates?refresh=false")
        ).status_code == 404
        assert (await other.get("/api/lost-reports")).json() == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/claims", {"lost_report_id": 1, "found_item_id": 1}),
        ("POST", "/api/claims/1/pickup-code", {}),
        ("POST", "/api/deposits", {}),
        ("POST", "/api/deposit-drafts", {}),
        ("POST", "/api/deposit-drafts/1/retry", {}),
        ("POST", "/api/deposit-drafts/1/discard", {}),
        ("POST", "/api/deposit-drafts/1/confirm", {"category": "phone"}),
        ("POST", "/api/admin/claims/1/decision", {"decision": "approve"}),
        ("POST", "/api/admin/lockers/L1/reset", {}),
        ("POST", "/api/admin/lockers/L1/compartments/1/reset", {"expected_state": "free"}),
        ("POST", "/api/admin/items/1/retry-ai", {}),
        ("POST", "/api/admin/items/1/remove", {}),
        ("PUT", "/api/admin/items/1/attributes", {"category": "phone", "attributes": []}),
        ("POST", "/api/device/codes/validate", {"device_id": "locker_01", "code": "123456"}),
        ("POST", "/locker/validate", {"device_id": "locker_01", "code": "123456"}),
        ("POST", "/api/device/compartments/1/state", {"device_id": "locker_01", "occupied": True}),
        ("POST", "/api/device/heartbeat", {"device_id": "locker_01"}),
        ("GET", "/api/lockers/L1", None),
        ("GET", "/api/admin/lockers", None),
        ("GET", "/api/lost-reports/1/candidates", None),
        ("GET", "/api/lost-reports/1/candidates?refresh=true", None),
    ],
)
async def test_mock_reporting_blocks_every_non_reporting_operation(mock_client, method, path, body):
    response = await mock_client.request(method, path, json=body)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "mock_reporting_scope"
    async with db.SessionLocal() as session:
        for model in (Claim, AccessCode, FoundItem, ItemPhoto, Locker, Compartment):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_mock_permission_does_not_grant_real_ai_readiness(mock_settings):
    with pytest.raises(AppError) as error:
        await readiness.require_ai_ready()
    assert error.value.code == "ai_unavailable"
    await readiness.require_report_ai_ready()


async def test_memory_databases_do_not_share_accounts_or_reports(mock_client):
    from app.modules.identity.models import User
    from app.modules.lost_reports.models import LostReport

    await register_mock_owner(mock_client)
    assert (await mock_client.post("/api/lost-reports", json=report())).status_code == 201
    independent = db._make_engine(MOCK_REPORTING_DATABASE_URL)
    try:
        async with independent.begin() as connection:
            await connection.run_sync(db.Base.metadata.create_all)
        async with async_sessionmaker(independent)() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 0
            assert await session.scalar(select(func.count()).select_from(LostReport)) == 0
    finally:
        await independent.dispose()
