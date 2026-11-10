import io
import os
import tempfile

# Test settings must be in place before the app is imported.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="pf-photos-")
os.environ["AI_PROVIDER"] = "mock"
os.environ["AI_RETRY_BASE_DELAY_S"] = "0"
os.environ["SECRET_KEY"] = "test-secret"

import httpx  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.identity import service as identity  # noqa: E402
from app.modules.locker import service as locker_service  # noqa: E402
from app.shared import ratelimit  # noqa: E402
from app.shared.ai.provider import set_ai_provider  # noqa: E402


@pytest.fixture(autouse=True)
async def database():
    async with db.engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(db.Base.metadata.drop_all)
        await conn.run_sync(db.Base.metadata.create_all)
    ratelimit.reset_all()
    set_ai_provider(None)
    yield


@pytest.fixture
async def session():
    async with db.SessionLocal() as s:
        yield s


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def new_client(app):
    """Factory for extra clients: each has its own cookie jar (finder, owner, admin...)."""
    clients = []

    async def make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(new_client):
    return await new_client()


@pytest.fixture
async def locker(session):
    """A two-compartment locker 'L1'. Returns (locker, device headers)."""
    lk, key = await locker_service.create_locker(session, "L1", "Library locker", "library", 2)
    return lk, {"X-Device-Key": key}


async def _login(new_client, session, email, role="owner"):
    await identity.register(session, email, "secret123", email.split("@")[0], role=role)
    c = await new_client()
    await c.post("/api/auth/login", json={"email": email, "password": "secret123"})
    return c


@pytest.fixture
async def owner(new_client, session):
    return await _login(new_client, session, "owner@test.com")


@pytest.fixture
async def other_owner(new_client, session):
    return await _login(new_client, session, "other@test.com")


@pytest.fixture
async def admin(new_client, session):
    return await _login(new_client, session, "admin@test.com", role="admin")


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "black").save(buf, "JPEG")
    return buf.getvalue()


PHONE_NOTE = "Black Samsung phone, cat sticker, serial ends 4821"


async def deposit(client, note=PHONE_NOTE, location="library", n_photos=1):
    return await client.post(
        "/api/deposits",
        data={"locker_code": "L1", "location": location, "note": note},
        files=[("photos", (f"p{i}.jpg", jpeg(), "image/jpeg")) for i in range(n_photos)],
    )


async def deposit_and_store(client, device_headers, **kw) -> int:
    """Finder deposits, then the locker reports the item inside. Returns the item id."""
    r = await deposit(client, **kw)
    assert r.status_code == 201, r.text
    body = r.json()
    await client.post(
        "/api/device/codes/validate",
        json={"device_id": "locker_01", "code": body["deposit_code"]},
        headers=device_headers,
    )
    await client.post(
        f"/api/device/compartments/{body['compartment']}/state",
        json={"device_id": "locker_01", "occupied": True},
        headers=device_headers,
    )
    return body["item_id"]
