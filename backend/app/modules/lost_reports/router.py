from fastapi import APIRouter

from app.modules.identity.deps import CurrentUser, SessionDep
from app.modules.lost_reports import service
from app.modules.lost_reports.schemas import LostReportIn, LostReportOut

router = APIRouter(prefix="/api/lost-reports", tags=["lost reports"])


@router.post("", response_model=LostReportOut, status_code=201)
async def create(body: LostReportIn, user: CurrentUser, session: SessionDep):
    return await service.create(session, user.id, body.model_dump())


@router.get("", response_model=list[LostReportOut])
async def list_mine(user: CurrentUser, session: SessionDep):
    return await service.list_mine(session, user.id)


@router.get("/{report_id}", response_model=LostReportOut)
async def get_one(report_id: int, user: CurrentUser, session: SessionDep):
    return await service.get_own(session, report_id, user.id)
