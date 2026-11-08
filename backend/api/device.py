"""Locker API for the ESP32 (proposal 9.5).

Every request needs the header "X-Device-Key". The body uses the same format as the
current firmware: {"device_id": "locker_01", "code": "123456"}.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.database.models import Locker
from backend.services import locker as locker_service

router = APIRouter(prefix="/api/device", tags=["locker"])


class CodeRequest(BaseModel):
    device_id: str = Field(max_length=50)
    code: str = Field(min_length=1, max_length=12, pattern=r"^\d+$")


class CodeResponse(BaseModel):
    authorized: bool
    compartment: int | None
    action: str | None


class StateRequest(BaseModel):
    device_id: str = Field(max_length=50)
    occupied: bool  # IR sensor: is an item inside?


class StateResponse(BaseModel):
    compartment: int
    state: str


def _device(db: Session, device_id: str, device_key: str | None) -> Locker:
    locker = locker_service.authenticate_device(db, device_id, device_key)
    if locker is None:
        raise HTTPException(status_code=401, detail="Unknown device or wrong device key.")
    return locker


@router.post("/codes/validate", response_model=CodeResponse)
def validate_code(
    request: CodeRequest,
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Keypad code -> open or deny. The answer says which compartment opens."""
    locker = _device(db, request.device_id, x_device_key)
    result = locker_service.check_code(db, locker, request.code)
    db.commit()  # also stores failed attempts in the audit log
    return CodeResponse(authorized=result.authorized, compartment=result.compartment, action=result.action)


@router.post("/compartments/{number}/state", response_model=StateResponse)
def compartment_state(
    number: int,
    request: StateRequest,
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Door closed and # pressed: the ESP32 reports what the IR sensor sees."""
    locker = _device(db, request.device_id, x_device_key)
    try:
        compartment = locker_service.report_compartment_state(db, locker, number, request.occupied)
    except locker_service.LockerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return StateResponse(compartment=compartment.number, state=compartment.state.value)
