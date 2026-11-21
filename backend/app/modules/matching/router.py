from fastapi import APIRouter, Depends, Query

from app.modules.identity.deps import CurrentUser, SessionDep
from app.modules.matching import service
from app.modules.matching.schemas import CandidateOut
from app.shared.ai.readiness import require_report_ai_ready

router = APIRouter(tags=["matching"])


@router.get(
    "/api/lost-reports/{report_id}/candidates",
    response_model=list[CandidateOut],
    dependencies=[Depends(require_report_ai_ready)],
)
async def candidates(
    report_id: int,
    user: CurrentUser,
    session: SessionDep,
    refresh: bool = True,
    offset: int = Query(default=0, ge=0),
):
    if not refresh:
        return await service.cached_candidates(session, report_id, user.id, offset)
    return await service.candidates(session, report_id, user.id, offset)
