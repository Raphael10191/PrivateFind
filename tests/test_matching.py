"""Unit tests for the Match Score (6.6) and the wait times (8.3)."""
from datetime import datetime, timedelta

from sqlalchemy import select

from backend.database.models import (
    Claim,
    ClaimStatus,
    FoundItem,
    FoundItemStatus,
    ItemAttribute,
    LostReport,
    MatchCandidate,
    User,
    Visibility,
)
from backend.database.seed import seed_demo
from backend.services import attempts, embeddings, matching

NOW = datetime(2026, 10, 29, 12, 0)


def test_location_score():
    assert matching.location_score("Library, entrance", "library, entrance") == 100
    assert matching.location_score("Gwanggaeto Hall, 3rd floor", "Gwanggaeto Hall, 5th floor") == 60
    assert matching.location_score("Gwanggaeto Hall", "Hall of Gwanggaeto") == 30
    assert matching.location_score("Library", "Student Center") == 0


def test_time_score():
    start, end = NOW - timedelta(hours=4), NOW
    assert matching.time_score(start, end, NOW - timedelta(hours=1)) == 100
    assert matching.time_score(start, end, NOW + timedelta(days=1)) == 80
    assert matching.time_score(start, end, NOW + timedelta(days=10)) == 0
    assert matching.time_score(start, end, start - timedelta(days=1)) == 0


def test_attribute_score_uses_only_public_attributes():
    item = FoundItem(location="x", found_at=NOW)
    item.attributes = [
        ItemAttribute(name="colour", value="black", visibility=Visibility.PUBLIC, weight=1),
        ItemAttribute(name="brand", value="Adidas", visibility=Visibility.PUBLIC, weight=3),
        ItemAttribute(name="contents", value="student card", visibility=Visibility.PRIVATE, weight=3),
    ]
    report = LostReport(description="black wallet with a student card", brand_model=None, unique_marks=None)
    assert matching.attribute_score(report, item) == 25.0  # only "black" (1 of 4)


def test_total_is_rescaled_without_semantic():
    parts = matching.PartialScores(category=100, location=100, time=100, attributes=100)
    assert parts.total() == 100
    parts = matching.PartialScores(category=100, location=60, time=100, attributes=0)
    assert parts.total() == 61.2


def test_semantic_score():
    item = FoundItem(category="wallet", location="x", found_at=NOW)
    item.attributes = [
        ItemAttribute(name="colour", value="black", visibility=Visibility.PUBLIC, weight=1),
        ItemAttribute(name="contents", value="student card", visibility=Visibility.PRIVATE, weight=3),
    ]
    same = LostReport(category="wallet", description="black")
    other = LostReport(category="umbrella", description="blue")
    assert embeddings.semantic_score(same, item) == 100
    assert embeddings.semantic_score(other, item) == 0
    # private attributes are not part of the item text
    assert "student" not in embeddings.item_text(item)


def test_demo_data_matches_wallet_not_umbrella(db):
    seed_demo(db)
    report = db.scalar(select(LostReport))
    top = matching.update_candidates(db, report)
    assert len(top) == 1
    assert top[0].found_item.category == "wallet"
    assert top[0].total_score == 100
    # all partial scores are stored (explainable score)
    stored = db.scalar(select(MatchCandidate))
    assert stored.category_score == 100 and stored.attribute_score == 100
    assert "contents" not in str(matching.public_summary(top[0]))


def test_returned_items_are_not_candidates(db):
    seed_demo(db)
    for item in db.scalars(select(FoundItem)):
        item.status = FoundItemStatus.RETURNED
    db.flush()
    assert matching.update_candidates(db, db.scalar(select(LostReport))) == []


def test_wait_time_grows_per_user_and_item(db):
    seed_demo(db)
    report = db.scalar(select(LostReport))
    owner = db.get(User, report.user_id)
    other = db.scalar(select(User).where(User.username == "admin"))
    match = matching.update_candidates(db, report)[0]
    item_id = match.item_id

    assert attempts.claim_wait_until(db, owner.user_id, item_id) is None

    # failed claims of ANOTHER user never make it harder for the owner
    for _ in range(3):
        db.add(Claim(match_candidate=match, user=other, status=ClaimStatus.REJECTED, created_at=datetime.now()))
    db.flush()
    assert attempts.claim_wait_until(db, owner.user_id, item_id) is None
    wait_other = attempts.claim_wait_until(db, other.user_id, item_id)
    assert timedelta(minutes=19) < wait_other - datetime.now() <= timedelta(minutes=20)
    assert attempts.next_attempt_no(db, other.user_id, item_id) == 4
