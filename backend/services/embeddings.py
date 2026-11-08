"""Semantic similarity for the Match Score (work package 7.2).

Idea: the owner's report and the item are turned into two texts. Each text becomes a
vector (embedding). The more similar the two vectors are, the more similar is the meaning.
We measure this with the cosine similarity (1 = same direction, 0 = nothing in common).

get_embedding() is a SIMPLE MOCK for now: it only counts words, so it finds the same
words, not words with the same meaning. Zohidjon replaces it with the call to the
hosted embedding API (work package 7.1). The API returns a list of numbers instead of
a dict, so cosine_similarity() then uses zip(a, b) instead of the word keys.
"""
import math
import re

from backend.database.models import FoundItem, LostReport, Visibility


def get_embedding(text: str) -> dict[str, float]:
    """MOCK: word -> how often it appears. TODO (Zohidjon): call the embedding API here."""
    vector: dict[str, float] = {}
    for word in re.findall(r"[a-z0-9가-힣]+", text.lower()):
        vector[word] = vector.get(word, 0) + 1
    return vector


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(value * b.get(key, 0) for key, value in a.items())
    length_a = math.sqrt(sum(v * v for v in a.values()))
    length_b = math.sqrt(sum(v * v for v in b.values()))
    if length_a == 0 or length_b == 0:
        return 0.0
    return dot / (length_a * length_b)


def report_text(report: LostReport) -> str:
    parts = [report.category, report.brand_model, report.description, report.unique_marks]
    return " ".join(p for p in parts if p)


def item_text(item: FoundItem) -> str:
    """Only public data. Private attributes are never used for matching."""
    public = [a.value for a in item.attributes if a.visibility == Visibility.PUBLIC]
    return " ".join([item.category or ""] + public)


def semantic_score(report: LostReport, item: FoundItem) -> float:
    """0-100: how similar the meaning of report and item is."""
    similarity = cosine_similarity(get_embedding(report_text(report)), get_embedding(item_text(item)))
    return round(100 * similarity, 1)
