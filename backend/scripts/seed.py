"""Create the first admin and a demo locker. Safe to run more than once.

    uv run python -m scripts.seed --admin-email admin@privatefind.local --admin-password <pw>

Prints the locker's device key once: put it in the ESP32 firmware config.
"""

import argparse
import asyncio

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.db import SessionLocal
from app.modules.identity import service as identity
from app.modules.identity.models import User
from app.modules.locker import service as locker_service
from app.modules.locker.models import Locker


async def main(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(User).where(User.email == args.admin_email.lower())):
            print(f"admin {args.admin_email} already exists")
        else:
            await identity.register(
                session, args.admin_email, args.admin_password, "Administrator", role="admin"
            )
            print(f"created admin {args.admin_email}")

        existing = await session.scalar(select(Locker).where(Locker.device_id == args.device_id))
        if existing:
            existing.code = args.locker_code
            existing.name = args.locker_name
            await session.commit()
            print(f"locker {args.locker_code} already exists (keep its existing device key)")
        else:
            _, key = await locker_service.create_locker(
                session, args.locker_code, args.locker_name, args.locker_location, 1, args.device_id
            )
            print(f"created locker {args.locker_code} with 1 compartment")
            print(f"DEVICE KEY (store it in the firmware, shown once): {key}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--admin-email", required=True)
    p.add_argument("--admin-password", required=True)
    p.add_argument("--device-id", default="locker_01")
    p.add_argument("--locker-code", default="L1")
    p.add_argument("--locker-name", default="Library smart locker")
    p.add_argument("--locker-location", default="library")
    asyncio.run(main(p.parse_args()))
