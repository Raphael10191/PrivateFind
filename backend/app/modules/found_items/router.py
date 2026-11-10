from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.modules.found_items import service
from app.modules.found_items.models import FoundItem
from app.modules.found_items.schemas import AdminItemOut, AttributesIn, DepositOut
from app.modules.identity.deps import AdminUser, SessionDep
from app.modules.locker import service as locker_service
from app.shared.ratelimit import deposit_limiter

router = APIRouter(tags=["found items"])


@router.post("/api/deposits", response_model=DepositOut, status_code=201)
async def deposit(
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    locker_code: Annotated[str, Form(max_length=20)],
    location: Annotated[str, Form(max_length=50)],
    photos: Annotated[list[UploadFile], File()],
    note: Annotated[str, Form(max_length=500)] = "",
    finder_contact: Annotated[str | None, Form(max_length=200)] = None,
):
    """Public (finder, no account). AI extraction runs after the response is sent."""
    ip = request.client.host if request.client else "unknown"
    if not deposit_limiter.hit(ip):
        raise AppError(429, "rate_limited", "Too many deposits. Please try again later.")
    files = [(await p.read(), p.content_type) for p in photos]
    item, issued = await service.submit_deposit(
        session, locker_code, location, note, finder_contact, files
    )
    background.add_task(service.run_extraction, item.id)
    return DepositOut(
        item_id=item.id,
        compartment=issued.compartment,
        deposit_code=issued.code,
        expires_at=issued.expires_at,
    )


# ---------- admin ----------


async def _admin_out(session, item: FoundItem) -> AdminItemOut:
    compartment = await locker_service.compartment_for_item(session, item.id)
    return AdminItemOut.model_validate(
        {
            **{c: getattr(item, c) for c in AdminItemOut.model_fields if hasattr(item, c)},
            "attributes": item.attributes,
            "photo_ids": [p.id for p in item.photos],
            "compartment": compartment.number if compartment else None,
        }
    )


@router.get("/api/admin/items", response_model=list[AdminItemOut], tags=["admin"])
async def list_items(
    _: AdminUser, session: SessionDep, status: str | None = None, ai_status: str | None = None
):
    return [
        await _admin_out(session, i) for i in await service.list_items(session, status, ai_status)
    ]


@router.get("/api/admin/items/{item_id}", response_model=AdminItemOut, tags=["admin"])
async def get_item(item_id: int, _: AdminUser, session: SessionDep):
    return await _admin_out(session, await service.get_item(session, item_id))


@router.put("/api/admin/items/{item_id}/attributes", response_model=AdminItemOut, tags=["admin"])
async def replace_attributes(
    item_id: int, body: AttributesIn, admin: AdminUser, session: SessionDep
):
    item = await service.replace_attributes(
        session,
        item_id,
        admin.id,
        body.category,
        body.public_summary,
        [a.model_dump(exclude={"confidence"}) for a in body.attributes],
    )
    return await _admin_out(session, item)


@router.post("/api/admin/items/{item_id}/retry-ai", status_code=202, tags=["admin"])
async def retry_ai(
    item_id: int, admin: AdminUser, session: SessionDep, background: BackgroundTasks
):
    await service.reset_for_retry(session, item_id, admin.id)
    background.add_task(service.run_extraction, item_id)
    return {"ok": True}


@router.get("/api/admin/items/{item_id}/photos/{photo_id}", tags=["admin"])
async def photo(item_id: int, photo_id: int, _: AdminUser, session: SessionDep):
    return FileResponse(
        await service.photo_file(session, item_id, photo_id), media_type="image/jpeg"
    )
