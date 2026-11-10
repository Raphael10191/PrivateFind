"""Fixed vocabularies shared by the AI schema, lost reports, matching and claims."""

from typing import Literal

Category = Literal[
    "phone", "wallet", "keys", "bag", "laptop", "tablet", "headphones", "bottle",
    "umbrella", "clothing", "id_card", "glasses", "book", "jewelry", "other",
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

STRENGTH_WEIGHT = {"strong": 3, "distinctive": 2, "generic": 1}

# Evidence types that must match exactly; a mismatch is a critical conflict.
CRITICAL_TYPES = {"serial_suffix"}

# Items too common to auto-approve, whatever the evidence.
GENERIC_CATEGORIES = {"umbrella", "bottle", "clothing", "book"}
