import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.errors import AppError
from app.shared import audit, storage
from app.shared.ai.mock import MockAIProvider
from app.shared.ratelimit import RateLimiter


def make_jpeg(size=(2400, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "blue").save(buf, "JPEG")
    return buf.getvalue()


def test_save_photo_resizes_and_stores():
    name = storage.save_photo(make_jpeg(), "image/jpeg")
    img = Image.open(storage.photo_path(name))
    assert max(img.size) == storage.MAX_SIDE_PX


@pytest.mark.parametrize("data,ctype", [(b"x", "image/gif"), (b"not an image", "image/png")])
def test_save_photo_rejects_bad_files(data, ctype):
    with pytest.raises(AppError):
        storage.save_photo(data, ctype)


def test_rate_limiter():
    rl = RateLimiter(limit=2, window_s=60)
    assert rl.hit("a") and rl.hit("a")
    assert not rl.hit("a")
    assert rl.hit("b")


async def test_audit_log_written(session):
    audit.log(session, "test_action", "thing", 7, actor_type="system", note="hi")
    await session.commit()
    row = (await session.execute(select(audit.AuditLog))).scalar_one()
    assert (row.action, row.entity_id, row.details) == ("test_action", 7, {"note": "hi"})


async def test_mock_ai_extraction():
    ai = MockAIProvider()
    ex = await ai.extract_attributes([], "Navy Samsung phone, cat sticker, serial ends 99214821")
    assert (ex.category, ex.color, ex.brand) == ("phone", "blue", "Samsung")
    types = {a.type: a.value for a in ex.private_attributes}
    assert types["serial_suffix"] == "4821"
    assert "sticker" in types["sticker_or_mark"]


async def test_mock_ai_compare():
    ai = MockAIProvider()
    s = await ai.compare_texts("black wallet leather", ["leather wallet black", "red umbrella"])
    assert s[0] > 0.9 and s[1] == 0.0
