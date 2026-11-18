from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LockerInfo(BaseModel):
    code: str
    name: str
    location: str
    free_compartments: int
    locations: list[str]


class CompartmentOverview(BaseModel):
    number: int
    state: str
    active_item_id: int | None = None


class CompartmentResetIn(BaseModel):
    expected_state: str
    expected_item_id: int | None


class LockerOverview(BaseModel):
    code: str
    name: str
    location: str
    device_id: str
    last_seen_at: datetime | None
    compartments: list[CompartmentOverview] = Field(default_factory=list)


class CodeIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=50)
    code: str = Field(pattern=r"^\d{6}$")


class CodeResult(BaseModel):
    authorized: bool
    compartment: int | None = None
    action: Literal["deposit", "pickup"] | None = None


class StateIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=50)
    occupied: bool


class StateResult(BaseModel):
    compartment: int
    state: str


class HeartbeatIn(BaseModel):
    firmware_version: str | None = None
