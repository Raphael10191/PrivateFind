from fastapi import APIRouter

from app.modules.identity.deps import CurrentUser, SessionDep
from app.modules.matching import service
from app.modules.matching.schemas import CandidateOut

router = APIRouter(tags=["matching"])


@router.get("/api/lost-reports/{report_id}/candidates", response_model=list[CandidateOut])
async def candidates(report_id: int, user: CurrentUser, session: SessionDep, refresh: bool = True):
    if not refresh:
        return await service.cached_candidates(session, report_id, user.id)
    return await service.candidates(session, report_id, user.id)
