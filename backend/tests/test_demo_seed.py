import pytest
from PIL import Image
from sqlalchemy import select

from app.modules.found_items.models import FoundItem
from app.modules.locker import service
from app.modules.locker.models import Compartment, Locker
from app.shared import storage
from scripts.demo_seed import DEVICE_ID, ITEMS, seed_demo


async def test_seed_demo_reuses_items_and_creates_private_photos(session):
    await seed_demo(session)
    await seed_demo(session)
    locker = await session.scalar(select(Locker).where(Locker.code == "L2"))
    assert locker.device_id == DEVICE_ID
    compartments = (
        await session.scalars(
            select(Compartment)
            .where(Compartment.locker_id == locker.id)
            .order_by(Compartment.number)
        )
    ).all()
    assert [(c.number, c.state) for c in compartments] == [(i, "occupied") for i in range(1, 6)]

    items = (
        await session.scalars(
            select(FoundItem).where(FoundItem.locker_id == locker.id).order_by(FoundItem.id)
        )
    ).all()
    assert [item.attr("model") for item in items] == [spec["model"] for spec in ITEMS]
    for item in items:
        assert item.status == "open" and item.ai_status == "done" and item.private_attributes()
        assert len(item.photos) == 1
        with Image.open(storage.photo_path(item.photos[0].file_name)) as image:
            assert image.format == "JPEG" and image.size == (600, 600)


async def test_seed_demo_leaves_existing_non_demo_locker_in_place(session):
    await service.create_locker(session, "L2", "Existing locker", "library")
    with pytest.raises(ValueError, match="another device"):
        await seed_demo(session)
    locker = await session.scalar(select(Locker).where(Locker.code == "L2"))
    assert locker.name == "Existing locker"
    assert list(await session.scalars(select(FoundItem))) == []
