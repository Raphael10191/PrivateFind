"""Test data for local development.

Run from the project folder (after "alembic upgrade head"):
    python -m backend.database.seed            # locker with 1 compartment, admin, test owner
    python -m backend.database.seed --demo     # + two found items and a lost report for matching

The script can run several times: it only adds what is missing.
ONLY for development. Never use these passwords on a real server.
"""
import argparse
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.database import SessionLocal
from backend.database.models import (
    AiStatus,
    AttributeSource,
    Compartment,
    CompartmentState,
    FoundItem,
    FoundItemStatus,
    ItemAttribute,
    Locker,
    LostReport,
    User,
    UserRole,
    Visibility,
)
from backend.security import hash_password, hash_token

DEVICE_ID = "locker_01"  # same as in the ESP32 firmware
DEVICE_KEY = os.getenv("DEVICE_KEY", "dev-locker-key")

USERS = [
    # username, e-mail, password, role
    ("admin", "admin@privatefind.local", "admin1234", UserRole.ADMIN),
    ("testowner", "owner@privatefind.local", "owner1234", UserRole.OWNER),
]


def seed_base(db: Session) -> None:
    locker = db.scalar(select(Locker).where(Locker.device_id == DEVICE_ID))
    if locker is None:
        locker = Locker(
            device_id=DEVICE_ID,
            device_key_hash=hash_token(DEVICE_KEY),
            location="Student Center, 1st floor",
        )
        db.add(locker)
        db.flush()
        print(f"Locker '{DEVICE_ID}' created (locker_id={locker.locker_id}).")
    else:
        locker.device_key_hash = hash_token(DEVICE_KEY)  # key from .env always wins

    # Our prototype has only one compartment (team decision of 4 Nov)
    exists = db.scalar(select(Compartment).where(Compartment.locker_id == locker.locker_id))
    if exists is None:
        db.add(Compartment(locker_id=locker.locker_id, number=1, state=CompartmentState.FREE))
        print("Compartment 1 created.")

    for username, email, password, role in USERS:
        if db.scalar(select(User).where(User.username == username)) is None:
            db.add(User(username=username, email=email, password_hash=hash_password(password), role=role))
            print(f"User '{username}' created (password: {password}).")


def seed_demo(db: Session) -> None:
    """Two found items (not in a compartment) and one lost report, to try the Match Score."""
    if db.scalar(select(FoundItem).where(FoundItem.finder_note == "seed demo")) is not None:
        print("Demo data already exists.")
        return

    now = datetime.now()
    wallet = FoundItem(
        category="wallet", location="Gwanggaeto Hall, 3rd floor", finder_note="seed demo",
        found_at=now - timedelta(hours=2), status=FoundItemStatus.OPEN, ai_status=AiStatus.DONE,
    )
    wallet.attributes = [
        ItemAttribute(name="colour", value="black", confidence=0.95, visibility=Visibility.PUBLIC, weight=1),
        ItemAttribute(name="brand", value="Adidas", confidence=0.80, visibility=Visibility.PUBLIC, weight=2),
        ItemAttribute(name="material", value="leather", confidence=0.70, visibility=Visibility.PUBLIC, weight=1),
        ItemAttribute(name="contents", value="student card", visibility=Visibility.PRIVATE, weight=3,
                      source=AttributeSource.FINDER),
    ]
    umbrella = FoundItem(
        category="umbrella", location="Library, entrance", finder_note="seed demo",
        found_at=now - timedelta(hours=5), status=FoundItemStatus.OPEN, ai_status=AiStatus.DONE,
    )
    umbrella.attributes = [
        ItemAttribute(name="colour", value="blue", confidence=0.9, visibility=Visibility.PUBLIC, weight=1),
    ]
    db.add_all([wallet, umbrella])

    owner = db.scalar(select(User).where(User.username == "testowner"))
    db.add(
        LostReport(
            user_id=owner.user_id, category="wallet", location="Gwanggaeto Hall, 3rd floor",
            lost_from=now - timedelta(hours=4), lost_to=now - timedelta(hours=1),
            brand_model="Adidas", description="black leather wallet",
        )
    )
    db.flush()
    print("Demo data created: wallet + umbrella, lost report of 'testowner' for a wallet.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill the PrivateFind database with test data.")
    parser.add_argument("--demo", action="store_true", help="also add demo items for matching")
    args = parser.parse_args()

    with SessionLocal() as db:
        seed_base(db)
        db.flush()
        if args.demo:
            seed_demo(db)
        db.commit()
    print("Seed finished.")


if __name__ == "__main__":
    main()
