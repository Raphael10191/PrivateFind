"""Shared availability check for AI-dependent actions."""

import asyncio
import io
import logging
from functools import cache
from time import monotonic

from PIL import Image

from app.core.config import get_settings
from app.core.errors import AppError
from app.shared.ai.provider import Photo, get_ai_provider

log = logging.getLogger(__name__)
OFFLINE_MESSAGE = "The AI service is temporarily unavailable. Please try again when it is back."
_probe_lock = asyncio.Lock()
_last_check: tuple[str, bool, float] | None = None


@cache
def _probe_photo() -> Photo:
    # Exercise actual vision inference without sending user photos or retaining a draft.
    with io.BytesIO() as buffer:
        Image.new("RGB", (128, 128), "blue").save(buffer, "JPEG")
        return Photo(buffer.getvalue())


def mark_ai_unavailable() -> None:
    global _last_check
    _last_check = (get_settings().ai_provider, False, monotonic() + 5)


async def ai_status() -> dict[str, str | bool]:
    global _last_check
    provider = get_settings().ai_provider
    if provider == "mock":
        return {"provider": provider, "available": False}

    async with _probe_lock:
        if not _last_check or _last_check[0] != provider or monotonic() >= _last_check[2]:
            try:
                await asyncio.wait_for(
                    get_ai_provider().verify_photos([_probe_photo()], "The test card is blue."),
                    timeout=12,
                )
            except Exception as exc:
                log.warning("AI readiness check failed for %s: %s", provider, type(exc).__name__)
                mark_ai_unavailable()
            else:
                _last_check = (provider, True, monotonic() + 20)
        return {"provider": provider, "available": _last_check[1]}


async def require_ai_ready() -> None:
    if not (await ai_status())["available"]:
        raise AppError(503, "ai_unavailable", OFFLINE_MESSAGE)
