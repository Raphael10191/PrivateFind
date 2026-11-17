from fastapi import APIRouter, BackgroundTasks

from app.modules.identity.deps import CurrentUser, SessionDep
from app.modules.lost_reports import service
from app.modules.lost_reports.schemas import LostReportIn, LostReportOut
from app.modules.matching.service import refresh_for_report

router = APIRouter(prefix="/api/lost-reports", tags=["lost reports"])


@router.post("", response_model=LostReportOut, status_code=201)
async def create(
    body: LostReportIn, user: CurrentUser, session: SessionDep, background: BackgroundTasks
):
    report = await service.create(session, user.id, body.model_dump())
    background.add_task(refresh_for_report, report.id, user.id)
    return report


@router.get("", response_model=list[LostReportOut])
async def list_mine(user: CurrentUser, session: SessionDep):
    return await service.list_mine(session, user.id)


@router.get("/{report_id}", response_model=LostReportOut)
async def get_one(report_id: int, user: CurrentUser, session: SessionDep):
    return await service.get_own(session, report_id, user.id)
