from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.identity.deps import SessionDep
from app.modules.locker import service
from app.modules.locker.models import Locker
from app.modules.locker.schemas import (
    CodeIn,
    CodeResult,
    HeartbeatIn,
    LockerInfo,
    StateIn,
    StateResult,
)

router = APIRouter(tags=["locker"])


async def current_locker(
    session: SessionDep, x_device_key: Annotated[str | None, Header()] = None
) -> Locker:
    locker = await service.locker_by_device_key(session, x_device_key) if x_device_key else None
    if locker is None:
        raise AppError(401, "invalid_device_key", "Unknown device.")
    return locker


DeviceLocker = Annotated[Locker, Depends(current_locker)]


@router.get("/api/lockers/{locker_code}", response_model=LockerInfo)
async def locker_info(locker_code: str, session: SessionDep):
    """Public: shown on the finder's QR page before the deposit form."""
    locker = await service.get_locker(session, locker_code)
    free = await service.free_compartments(session, locker.id)
    await session.commit()
    return LockerInfo(
        code=locker.code,
        name=locker.name,
        location=locker.location,
        free_compartments=free,
        locations=get_settings().locations,
    )


@router.post("/api/device/codes/validate", response_model=CodeResult, tags=["device"])
@router.post("/locker/validate", response_model=CodeResult, include_in_schema=False)
async def validate_code(body: CodeIn, locker: DeviceLocker, session: SessionDep):
    _check_device_id(locker, body.device_id)
    return await service.validate_code(session, locker, body.code)


@router.post("/api/device/compartments/{number}/state", response_model=StateResult, tags=["device"])
async def report_state(number: int, body: StateIn, locker: DeviceLocker, session: SessionDep):
    _check_device_id(locker, body.device_id)
    return await service.report_state(session, locker, number, body.occupied)


@router.post("/api/device/heartbeat", tags=["device"])
async def heartbeat(body: HeartbeatIn, locker: DeviceLocker, session: SessionDep):
    server_time = await service.heartbeat(session, locker)
    return {"ok": True, "server_time": server_time}


def _check_device_id(locker: Locker, device_id: str) -> None:
    if locker.device_id != device_id:
        raise AppError(401, "invalid_device_key", "Unknown device.")
