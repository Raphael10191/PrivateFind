from datetime import date

from pydantic import BaseModel


class Breakdown(BaseModel):
    category: float
    location: float
    time: float
    attributes: float
    semantic: float


class CandidateOut(BaseModel):
    """Public data only: no photos, no private attributes, no finder details."""

    found_item_id: int
    score: int
    breakdown: Breakdown
    category: str
    color: str | None
    location: str
    found_date: date
    public_summary: str | None
