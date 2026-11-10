from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.modules.lost_reports.models import LostReport
from app.shared import audit


async def create(session: AsyncSession, owner_id: int, data: dict) -> LostReport:
    if data["location"] not in get_settings().locations:
        raise AppError(422, "invalid_location", "Unknown location.")
    data["lost_at"] = data["lost_at"].replace(tzinfo=None)  # stored as naive UTC
    data["lost_to"] = data["lost_at"]
    data["brand_model"] = " ".join(filter(None, [data.get("brand"), data.get("model")])) or None
    report = LostReport(owner_id=owner_id, **data)
    session.add(report)
    await session.flush()
    audit.log(
        session,
        "lost_report_created",
        "lost_report",
        report.id,
        actor_type="user",
        actor_id=owner_id,
    )
    await session.commit()
    return report


async def list_mine(session: AsyncSession, owner_id: int) -> list[LostReport]:
    return list(
        await session.scalars(
            select(LostReport).where(LostReport.owner_id == owner_id).order_by(LostReport.id.desc())
        )
    )


async def get_own(session: AsyncSession, report_id: int, owner_id: int) -> LostReport:
    """Another user's report looks exactly like a missing one."""
    report = await session.get(LostReport, report_id)
    if report is None or report.owner_id != owner_id:
        raise not_found("Lost report")
    return report
