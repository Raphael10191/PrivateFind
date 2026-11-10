"""Private photo storage. Photos live outside /static and are never served publicly."""

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import AppError

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIDE_PX = 1600


def save_photo(data: bytes, content_type: str | None) -> str:
    """Validate, resize and re-encode as JPEG (drops EXIF/GPS). Returns the stored file name."""
    settings = get_settings()
    if content_type not in ALLOWED_TYPES:
        raise AppError(422, "invalid_photo", "Photos must be JPEG, PNG or WebP.")
    if len(data) > settings.max_photo_bytes:
        raise AppError(422, "invalid_photo", "Each photo must be 5 MB or smaller.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError(422, "invalid_photo", "File is not a valid image.") from exc

    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    name = f"{uuid.uuid4().hex}.jpg"
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    img.save(settings.storage_dir / name, "JPEG", quality=85)
    return name


def photo_path(name: str) -> Path:
    return get_settings().storage_dir / name


def read_photo(name: str) -> bytes:
    return photo_path(name).read_bytes()
