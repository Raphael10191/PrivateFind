from typing import Literal

from pydantic import BaseModel, Field


class LockerInfo(BaseModel):
    code: str
    name: str
    location: str
    free_compartments: int
    locations: list[str]


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
