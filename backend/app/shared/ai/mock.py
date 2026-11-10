"""Deterministic stand-in for the AI provider. Reads attributes from the finder's note only."""

import re
from typing import get_args

from app.shared.ai.provider import Photo
from app.shared.ai.schemas import Extraction, PrivateAttribute
from app.shared.vocab import Category, Color

_CATEGORY_WORDS = {
    "phone": ["phone", "iphone", "galaxy", "smartphone"],
    "wallet": ["wallet", "purse", "cardholder"],
    "keys": ["key", "keys", "keychain"],
    "bag": ["bag", "backpack", "tote"],
    "laptop": ["laptop", "macbook", "notebook computer"],
    "tablet": ["tablet", "ipad"],
    "headphones": ["headphones", "earbuds", "airpods", "earphones"],
    "bottle": ["bottle", "tumbler", "flask"],
    "umbrella": ["umbrella"],
    "clothing": ["jacket", "hoodie", "scarf", "hat", "coat", "sweater"],
    "id_card": ["student card", "id card", "card"],
    "glasses": ["glasses", "sunglasses"],
    "book": ["book", "textbook", "notebook"],
    "jewelry": ["ring", "necklace", "bracelet", "earring", "watch"],
}
_BRANDS = ["apple", "samsung", "lg", "sony", "xiaomi", "nike", "adidas", "dell", "lenovo", "hp"]
_COLOR_ALIASES = {"navy": "blue", "dark blue": "blue", "grey": "gray", "rose": "pink"}
_STOPWORDS = {"the", "and", "with", "has", "have", "for", "near", "found", "lost", "was", "this"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2} - _STOPWORDS


class MockAIProvider:
    async def extract_attributes(self, photos: list[Photo], note: str) -> Extraction:
        text = note.lower()
        category = next(
            (c for c, words in _CATEGORY_WORDS.items() if any(w in text for w in words)), "other"
        )
        assert category in get_args(Category)

        color = None
        for alias, canonical in _COLOR_ALIASES.items():
            if alias in text:
                color = canonical
        if color is None:
            color = next((c for c in get_args(Color) if re.search(rf"\b{c}\b", text)), None)

        brand = next((b.title() for b in _BRANDS if re.search(rf"\b{b}\b", text)), None)

        private: list[PrivateAttribute] = []
        if m := re.search(r"serial\D*(\d{3,})", text):
            private.append(
                PrivateAttribute(
                    type="serial_suffix", value=m.group(1)[-4:], strength="strong", confidence=0.9
                )
            )
        if m := re.search(r"([a-z]+ )?sticker", text):
            private.append(
                PrivateAttribute(
                    type="sticker_or_mark", value=m.group(0), strength="distinctive", confidence=0.8
                )
            )
        if m := re.search(r"(cracked|scratched|dented|broken|torn) ?[a-z]*", text):
            private.append(
                PrivateAttribute(
                    type="damage", value=m.group(0).strip(), strength="distinctive", confidence=0.8
                )
            )
        if m := re.search(r"engraved ([a-z0-9 ]+)", text):
            private.append(
                PrivateAttribute(
                    type="engraving", value=m.group(1).strip(), strength="strong", confidence=0.8
                )
            )

        summary = " ".join(p for p in [color, brand, category.replace("_", " ")] if p)
        return Extraction(
            category=category,
            color=color,
            brand=brand,
            public_summary=summary.capitalize(),
            description=note,
            private_attributes=private,
            confidence=0.7,
        )

    async def compare_texts(self, query: str, candidates: list[str]) -> list[float]:
        q = _words(query)
        scores = []
        for c in candidates:
            w = _words(c)
            scores.append(round(len(q & w) / min(len(q), len(w)), 3) if q and w else 0.0)
        return scores
