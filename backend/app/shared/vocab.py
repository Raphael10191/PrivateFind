"""Fixed vocabularies shared by the AI schema, lost reports, matching and claims."""

from typing import Literal

Category = Literal[
    "phone", "wallet", "keys", "bag", "laptop", "tablet", "headphones", "bottle",
    "umbrella", "clothing", "id_card", "glasses", "book", "jewelry",
    "watch", "electronics", "other",
]  # fmt: skip

Color = Literal[
    "black", "white", "gray", "silver", "gold", "red", "orange", "yellow", "green",
    "blue", "purple", "pink", "brown", "beige", "multicolor",
]  # fmt: skip

# Private attribute / ownership evidence types
EvidenceType = Literal[
    "serial_suffix", "model", "sticker_or_mark", "damage", "contents",
    "accessory", "engraving", "other",
]  # fmt: skip

Visibility = Literal["public", "private"]
Strength = Literal["strong", "distinctive", "generic"]

# Evidence types that must match exactly; a mismatch is a critical conflict.
CRITICAL_TYPES = {"serial_suffix"}

CATEGORY_ALIASES = {
    "smartphone": "phone",
    "mobile phone": "phone",
    "handy": "phone",
    "elektronik": "electronics",
    "backpack": "bag",
    "rucksack": "bag",
    "earbuds": "headphones",
    "keychain": "keys",
    "smartwatch": "watch",
}


def category_key(value: str | None) -> str:
    key = (value or "other").strip().casefold().replace("_", " ")
    return CATEGORY_ALIASES.get(key, key.replace(" ", "_"))
