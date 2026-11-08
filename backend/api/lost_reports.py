"""Owner API: lost-item report and Match Score candidates (6.4 support, 6.6)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user, get_db, limit_by_ip
from backend.database.models import LostReport, User
from backend.services import lost_reports as report_service
from backend.services import matching

router = APIRouter(prefix="/api/lost-reports", tags=["owner"], dependencies=[Depends(limit_by_ip)])


class LostReportIn(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    location: str = Field(min_length=1, max_length=120)
    lost_from: datetime
    lost_to: datetime
    brand_model: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    unique_marks: str | None = Field(default=None, max_length=1000)


class LostReportOut(BaseModel):
    report_id: int
    category: str
    location: str
    lost_from: datetime
    lost_to: datetime
    status: str


class PublicAttribute(BaseModel):
    name: str
    value: str


class CandidateOut(BaseModel):
    match_id: int
    item_id: int
    category: str | None
    found_location: str
    found_date: str
    public_attributes: list[PublicAttribute]
    match_score: float


def _out(report: LostReport) -> LostReportOut:
    return LostReportOut(
        report_id=report.report_id,
        category=report.category,
        location=report.location,
        lost_from=report.lost_from,
        lost_to=report.lost_to,
        status=report.status.value,
    )


@router.post("", response_model=LostReportOut, status_code=201)
def create_report(
    request: LostReportIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        report = report_service.create_lost_report(db, user, **request.model_dump())
    except report_service.LostReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _out(report)


@router.get("", response_model=list[LostReportOut])
def my_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_out(r) for r in report_service.list_reports_of_user(db, user)]


@router.get("/{report_id}/candidates", response_model=list[CandidateOut])
def candidates(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Top 3 candidates with public data only. Recalculated on every call,
    so items deposited after the report also appear."""
    try:
        report = report_service.get_report_of_user(db, report_id, user)
    except report_service.LostReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    top = matching.update_candidates(db, report)
    db.commit()
    return [matching.public_summary(c) for c in top]
