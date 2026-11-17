"""Fixed mixed inventory for measuring retrieval and ranking separately from ownership."""

from datetime import timedelta

from app.core.db import utcnow
from app.modules.found_items.models import FoundItem, ItemAttribute
from tests.test_claims import make_report

ITEMS = [
    ("clothing", "Black plain cap"),
    ("phone", "Black iPhone without damage"),
    ("clothing", "Black plain cap"),
    ("phone", "Purple iPhone with undamaged rear camera and intact glass"),
    ("clothing", "Black plain cap"),
    ("clothing", "Black plain cap"),
    ("phone", "Black iPhone without damage"),
    ("keys", "Keyring with a round key and a small fox charm"),
    ("headphones", "White wireless earphones in a square charging case"),
    ("bag", "Blue canvas backpack with a repair across the strap"),
    ("wallet", "Silver laptop with two paint dots by the hinge"),
    ("other", None),
    ("phone", "Purple iPhone with a shattered camera corner and star-shaped crack"),
    ("clothing", "Black plain cap"),
    ("clothing", "Black plain cap"),
]

QUERIES = [
    ("phone", "Purple iPhone with a shattered camera corner and star-shaped crack", 12),
    ("phone", "Black iPhone without damage", 6),
    ("clothing", "Black plain cap", 13),
    ("keys", "Keyring with a round key and a small fox charm", 7),
    ("headphones", "White wireless earphones in a square charging case", 8),
    ("bag", "Blue canvas backpack with a repair across the strap", 9),
    ("laptop", "Silver laptop with two paint dots by the hinge", 10),
    ("other", "Object left near the entrance", 11),
]


async def test_matching_recall_on_mixed_inventory(owner, session):
    now = utcnow()
    items = [
        FoundItem(
            found_at=now,
            category=category,
            status="open",
            location="library",
            description=description,
            attributes=[ItemAttribute(name="color", value="black", visibility="public")]
            if "Black" in (description or "")
            else [],
        )
        for category, description in ITEMS
    ]
    # The last fixture has no attributes. A loose date and location still help.
    items[11].found_at = now - timedelta(days=3)
    items[11].ai_status = "failed"
    session.add_all(items)
    await session.commit()
    ranks = []
    for category, description, expected_index in QUERIES:
        options = {"lost_at": now - timedelta(days=3)} if expected_index == 11 else {}
        report_id = await make_report(
            owner,
            category=category,
            description=description,
            **{key: value.isoformat() for key, value in options.items()},
        )
        url = f"/api/lost-reports/{report_id}/candidates?refresh=false"
        first = await owner.get(url)
        second = await owner.get(url + "&offset=5")
        actual = [row["found_item_id"] for row in first.json() + second.json()]
        item_id = items[expected_index].id
        ranks.append(actual.index(item_id) + 1 if item_id in actual else None)
    recall_at_3 = sum(rank is not None and rank <= 3 for rank in ranks)
    recall_at_5 = sum(rank is not None and rank <= 5 for rank in ranks)
    print(f"Target ranks: {ranks}. Recall@3={recall_at_3}/8. Recall@5={recall_at_5}/8.")
    assert ranks[:7] == [1, 2, 5, 1, 1, 1, 1]
    assert ranks[7] is not None
    assert recall_at_3 >= 6 and recall_at_5 == 8
