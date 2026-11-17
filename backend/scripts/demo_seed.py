"""Seed the virtual demo locker with five sample items.

Run after migrations with python -m scripts.demo_seed from the backend directory.
"""

import asyncio
import io
from datetime import timedelta

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.db import SessionLocal, utcnow
from app.modules.found_items.models import ACTIVE_ITEM_STATUSES, FoundItem, ItemAttribute, ItemPhoto
from app.modules.locker import service as locker_service
from app.modules.locker.models import Compartment, Locker
from app.shared import audit, storage

LOCKER_CODE = "L2"
DEVICE_ID = "locker_virtual_02"

DISTINCTIVE, STRONG = "distinctive", "strong"
ITEMS = [
    dict(
        title="iPhone 18 Pro Max",
        bg=(25, 25, 30),
        hours=2,
        location="gym",
        category="phone",
        color="black",
        brand="Apple",
        model="iPhone 18 Pro Max",
        summary="Black Apple iPhone 18 Pro Max",
        description="Black Apple iPhone 18 Pro Max in a black leather case. "
        "Long scratch on the back glass. Lock screen wallpaper shows a mountain lake at sunset. "
        "Carrier SK Telecom, Korean language.",
        private=[
            ("damage", "scratch on back", DISTINCTIVE),
            ("sticker_or_mark", "mountain lake wallpaper", DISTINCTIVE),
            ("accessory", "black leather case", DISTINCTIVE),
            ("other", "SK Telecom carrier", DISTINCTIVE),
        ],
    ),
    dict(
        title="iPhone X",
        bg=(235, 235, 240),
        hours=5,
        location="library",
        category="phone",
        color="white",
        brand="Apple",
        model="iPhone X",
        summary="White Apple iPhone X",
        description="White Apple iPhone X, cracked screen in the top left corner. "
        "Family photo as wallpaper. Pink pop socket on the back. Carrier KT.",
        private=[
            ("damage", "cracked screen corner", DISTINCTIVE),
            ("sticker_or_mark", "family photo wallpaper", DISTINCTIVE),
            ("accessory", "pink pop socket", DISTINCTIVE),
            ("other", "KT carrier", DISTINCTIVE),
        ],
    ),
    dict(
        title="AirPods Pro",
        bg=(250, 250, 250),
        hours=3,
        location="gym",
        category="headphones",
        color="white",
        brand="Apple",
        model="AirPods Pro",
        summary="White Apple AirPods Pro case",
        description="White Apple AirPods Pro charging case with engraved initials J.K. "
        "on the front. Lid is scratched, left earbud is missing.",
        private=[
            ("engraving", "initials J.K.", STRONG),
            ("damage", "scratched lid", DISTINCTIVE),
            ("other", "left earbud missing", DISTINCTIVE),
        ],
    ),
    dict(
        title="Casio Watch",
        bg=(60, 60, 60),
        hours=8,
        location="cafeteria",
        category="jewelry",
        color="black",
        brand="Casio",
        model="Casio F-91W",
        summary="Black Casio digital watch",
        description="Black Casio F-91W digital wristwatch with black rubber strap. "
        "Display glass is scratched. Time is set one hour ahead.",
        private=[
            ("damage", "scratched display", DISTINCTIVE),
            ("accessory", "black rubber strap", DISTINCTIVE),
            ("other", "time set one hour ahead", DISTINCTIVE),
        ],
    ),
    dict(
        title="Apple Watch",
        bg=(255, 120, 40),
        hours=12,
        location="student_center",
        category="jewelry",
        color="black",
        brand="Apple",
        model="Apple Watch Series 10",
        summary="Black Apple Watch",
        description="Black Apple Watch Series 10 (midnight aluminium) with an orange sport band. "
        "Nike watch face, small crack at the bottom of the screen.",
        private=[
            ("accessory", "orange sport band", DISTINCTIVE),
            ("sticker_or_mark", "Nike watch face", DISTINCTIVE),
            ("damage", "small crack on screen", DISTINCTIVE),
        ],
    ),
]


def placeholder(title: str, bg: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (600, 600), bg)
    d = ImageDraw.Draw(img)
    fg = (255, 255, 255) if sum(bg) < 400 else (30, 30, 30)
    d.rectangle([40, 40, 560, 560], outline=fg, width=6)
    d.text((70, 260), "DEMO ITEM", fill=fg)
    d.text((70, 300), title, fill=fg)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def _seed(session: AsyncSession, created_photos: list[str]) -> None:
    locker = await session.scalar(
        select(Locker).where(Locker.code == LOCKER_CODE).with_for_update()
    )
    if locker is None:
        locker, _ = await locker_service.create_locker(
            session,
            LOCKER_CODE,
            "Student Center locker (virtual)",
            "student_center",
            len(ITEMS),
            DEVICE_ID,
            commit=False,
        )
    if locker.device_id != DEVICE_ID:
        raise ValueError(f"Locker {LOCKER_CODE} is already assigned to another device.")

    compartments = (
        await session.scalars(
            select(Compartment)
            .where(Compartment.locker_id == locker.id)
            .order_by(Compartment.number)
            .with_for_update()
        )
    ).all()
    if len(compartments) != len(ITEMS):
        raise ValueError(f"Expected {len(ITEMS)} compartments in locker {LOCKER_CODE}.")

    active = await session.scalars(
        select(FoundItem)
        .where(
            FoundItem.compartment_id.in_([comp.id for comp in compartments]),
            FoundItem.status.in_(ACTIVE_ITEM_STATUSES),
        )
        .with_for_update()
    )
    by_compartment = {}
    for item in active:
        if item.compartment_id in by_compartment:
            raise ValueError(f"Multiple items are active in a {LOCKER_CODE} compartment.")
        by_compartment[item.compartment_id] = item
    now = utcnow()
    for compartment, spec in zip(compartments, ITEMS, strict=True):
        note = f"[DEMO] {spec['title']}"
        found_at = now - timedelta(hours=spec["hours"])
        existing = by_compartment.get(compartment.id)
        if existing is not None:
            if existing.note != note or existing.status == "awaiting_deposit":
                raise ValueError(f"Compartment {compartment.number} already contains another item.")
            existing.found_at = found_at
            continue
        if compartment.state != "free":
            raise ValueError(f"Compartment {compartment.number} is unavailable.")

        attrs = [
            ItemAttribute(name=name, value=spec[name], visibility="public", confidence=0.9)
            for name in ("color", "brand", "model")
        ]
        attrs.extend(
            ItemAttribute(
                name=kind,
                value=value,
                visibility="private",
                strength=strength,
                confidence=0.85,
            )
            for kind, value, strength in spec["private"]
        )
        photo_name = storage.save_photo(placeholder(spec["title"], spec["bg"]), "image/png")
        created_photos.append(photo_name)
        item = FoundItem(
            locker_id=locker.id,
            compartment_id=compartment.id,
            category=spec["category"],
            location=spec["location"],
            note=note,
            found_at=found_at,
            status="open",
            ai_status="done",
            public_summary=spec["summary"],
            description=spec["description"],
            attributes=attrs,
            photos=[ItemPhoto(file_name=photo_name)],
        )
        session.add(item)
        compartment.state = "occupied"
        await session.flush()
        audit.log(session, "demo_item_seeded", "found_item", item.id, title=spec["title"])


async def seed_demo(session: AsyncSession) -> None:
    created_photos: list[str] = []
    try:
        async with session.begin():
            await _seed(session, created_photos)
    except BaseException:
        for name in created_photos:
            storage.photo_path(name).unlink(missing_ok=True)
        raise


async def main() -> None:
    async with SessionLocal() as session:
        await seed_demo(session)
    print(f"Locker {LOCKER_CODE} is ready with {len(ITEMS)} demo items.")


if __name__ == "__main__":
    asyncio.run(main())
