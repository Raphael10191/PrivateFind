from datetime import date

from pydantic import BaseModel


class CandidateOut(BaseModel):
    """Public data only: no photos, no private attributes, no finder details."""

    found_item_id: int
    category: str
    color: str | None
    location: str
    found_date: date
