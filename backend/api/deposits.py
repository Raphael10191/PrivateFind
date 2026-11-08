"""Finder API: QR code -> deposit session -> photos and answers (work package 6.3).

The finder needs no account. The deposit session token from the QR page is the only
proof that the request comes from someone standing at the locker.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from backend.api.deps import get_db, limit_by_ip
from backend.services import deposits as deposit_service

router = APIRouter(prefix="/api", tags=["finder"], dependencies=[Depends(limit_by_ip)])


class DepositSessionRequest(BaseModel):
    locker_id: int


class DepositSessionResponse(BaseModel):
    token: str
    expires_at: datetime


class DepositResponse(BaseModel):
    item_id: int
    compartment: int
    deposit_code: str
    code_expires_at: datetime


@router.post("/deposit-sessions", response_model=DepositSessionResponse, status_code=201)
def start_session(request: DepositSessionRequest, db: Session = Depends(get_db)):
    """Called by the QR page. Fails with 409 if no compartment is free."""
    try:
        session, token = deposit_service.start_deposit_session(db, request.locker_id)
    except deposit_service.NoFreeCompartmentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except deposit_service.DepositError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return DepositSessionResponse(token=token, expires_at=session.expires_at)


@router.post("/deposits", response_model=DepositResponse, status_code=201)
async def create_deposit(
    token: str = Form(..., max_length=100),
    location: str = Form(..., min_length=1, max_length=120),
    category: str | None = Form(default=None, max_length=40),
    note: str | None = Form(default=None, max_length=500),
    answers: str | None = Form(
        default=None,
        description='JSON list, e.g. [{"name": "contents", "value": "student card"}]',
    ),
    photos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Multipart form: three photos, quick answers, location and an optional note.

    Answer: compartment number and the one-time deposit code for the keypad.
    """
    try:
        answer_list = [deposit_service.FinderAnswer(**a) for a in json.loads(answers or "[]")]
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Answers have a wrong format.") from exc

    uploads = []
    for photo in photos:
        content = await photo.read()
        uploads.append(deposit_service.PhotoUpload(content=content, content_type=photo.content_type or ""))

    try:
        result = deposit_service.create_deposit(
            db,
            token=token,
            location=location,
            photos=uploads,
            answers=answer_list,
            category=category,
            finder_note=note,
        )
    except deposit_service.NoFreeCompartmentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except deposit_service.DepositError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return DepositResponse(
        item_id=result.item.item_id,
        compartment=result.compartment.number,
        deposit_code=result.deposit_code,
        code_expires_at=result.code_expires_at,
    )
