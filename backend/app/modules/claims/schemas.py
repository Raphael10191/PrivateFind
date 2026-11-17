from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.found_items.schemas import AttributeIO
from app.shared.vocab import EvidenceType


class EvidenceIn(BaseModel):
    type: EvidenceType
    value: str = Field(min_length=1, max_length=200)


class ClaimIn(BaseModel):
    lost_report_id: int
    found_item_id: int
    evidence: list[EvidenceIn] | None = Field(default=None, min_length=1, max_length=8)
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
        | None
    ) = None


class ClaimOut(BaseModel):
    id: int
    found_item_id: int
    lost_report_id: int
    status: str
    verification_state: str | None = None
    next_action: str | None = None
    message: str
    created_at: datetime
    compartment: int | None = None
    pickup_code: str | None = None  # only in the response that approves the claim
    pickup_expires_at: datetime | None = None


class PickupCodeOut(BaseModel):
    compartment: int
    pickup_code: str
    expires_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    value: str
    result: str
    similarity: float | None


class AdminClaimOut(BaseModel):
    id: int
    user_id: int
    found_item_id: int
    lost_report_id: int
    status: str
    verification_state: str | None = None
    next_action: str | None = None
    ownership_score: float | None
    critical_conflict: bool
    created_at: datetime
    decision_note: str | None
    evidence: list[EvidenceOut]
    item_summary: str | None
    item_private_attributes: list[AttributeIO]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "handed_over"]
    proof: (
        Literal[
            "dated_identifier_record",
            "live_device_control",
            "independent_record",
            "in_person_low_risk",
        ]
        | None
    ) = None
    note: str | None = Field(default=None, max_length=500)
