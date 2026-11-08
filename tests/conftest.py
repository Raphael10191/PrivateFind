"""Test setup: a temporary SQLite database instead of MySQL, so tests run without a server.

Run from the project folder:  pytest
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="privatefind-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEVICE_KEY"] = "test-device-key"
os.environ["SEMANTIC_ENABLED"] = "false"  # the score tests expect the rescaled version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.api.deps import get_db, reset_rate_limit  # noqa: E402
from backend.database.models import Base, User  # noqa: E402
from backend.database.seed import seed_base  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    reset_rate_limit()


@pytest.fixture()
def db_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        seed_base(db)
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture()
def db(db_factory):
    with db_factory() as session:
        yield session


@pytest.fixture()
def client(db_factory):
    def override():
        session = db_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def owner_headers(db):
    owner = db.scalar(select(User).where(User.username == "testowner"))
    return {"X-User-Id": str(owner.user_id)}


@pytest.fixture()
def admin_headers(db):
    admin = db.scalar(select(User).where(User.username == "admin"))
    return {"X-User-Id": str(admin.user_id)}


DEVICE = {"X-Device-Key": "test-device-key"}
