from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.shared.ai.schemas import ObservationState
from app.shared.vocab import Category, Strength, Visibility


class DepositOut(BaseModel):
    item_id: int
    compartment: int
    deposit_code: str
    expires_at: datetime


class DraftOut(BaseModel):
    item_id: int
    token: str


class DraftReview(BaseModel):
    status: str
    category: Category | None
    category_state: ObservationState | None
    suggest_photo: bool


class ConfirmDepositIn(BaseModel):
    category: Category | None = None


class AttributeIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(max_length=30)
    value: str = Field(max_length=200)
    visibility: Visibility
    strength: Strength | None = None
    confidence: float | None = None
    observation_state: ObservationState | None = None


class AdminItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    locker_id: int | None
    compartment: int | None = None
    location: str
    note: str | None
    finder_contact: str | None
    status: str
    found_at: datetime
    ai_status: str
    ai_attempts: int
    ai_error: str | None
    category: str | None
    public_summary: str | None
    description: str | None
    attributes: list[AttributeIO]
    photo_ids: list[int]


class AttributesIn(BaseModel):
    category: Category
    public_summary: str | None = Field(default=None, max_length=200)
    attributes: list[AttributeIO] = Field(max_length=30)
