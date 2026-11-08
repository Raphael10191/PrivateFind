"""Lost-item report of the owner (support for 6.4).

The owner has to report the lost item before any candidate is shown (proposal 4.2).
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import config
from backend.database.models import LostReport, LostReportStatus, User
from backend.services.audit import log_action


class LostReportError(Exception):
    pass


def create_lost_report(
    db: Session,
    user: User,
    category: str,
    location: str,
    lost_from: datetime,
    lost_to: datetime,
    brand_model: str | None = None,
    description: str | None = None,
    unique_marks: str | None = None,
) -> LostReport:
    category = category.strip().lower()
    if category not in config.CATEGORIES:
        raise LostReportError("Unknown category.")
    if not location.strip():
        raise LostReportError("Please enter where you lost the item.")
    if lost_to < lost_from:
        raise LostReportError("'Lost to' must be after 'lost from'.")
    if lost_from > datetime.now():
        raise LostReportError("The item cannot be lost in the future.")

    report = LostReport(
        user_id=user.user_id,
        category=category,
        location=location.strip(),
        lost_from=lost_from,
        lost_to=lost_to,
        brand_model=(brand_model or "").strip() or None,
        description=(description or "").strip() or None,
        unique_marks=(unique_marks or "").strip() or None,
        status=LostReportStatus.OPEN,
    )
    db.add(report)
    db.flush()
    log_action(db, "lost_report_created", "lost_report", report.report_id, user_id=user.user_id)
    return report


def get_report_of_user(db: Session, report_id: int, user: User) -> LostReport:
    """Owners only see their own reports."""
    report = db.get(LostReport, report_id)
    if report is None or report.user_id != user.user_id:
        raise LostReportError("Report not found.")
    return report


def list_reports_of_user(db: Session, user: User) -> list[LostReport]:
    return list(
        db.scalars(
            select(LostReport)
            .where(LostReport.user_id == user.user_id)
            .order_by(LostReport.created_at.desc(), LostReport.report_id.desc())
        )
    )
