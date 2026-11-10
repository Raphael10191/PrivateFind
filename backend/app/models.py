"""Imports every table so Base.metadata is complete (used by main.py, tests and Alembic)."""

from app.modules.claims.models import Claim, OwnershipEvidence  # noqa: F401
from app.modules.found_items.models import (  # noqa: F401
    DepositSession,
    FoundItem,
    ItemAttribute,
    ItemPhoto,
)
from app.modules.identity.models import User  # noqa: F401
from app.modules.locker.models import AccessCode, Compartment, Locker  # noqa: F401
from app.modules.lost_reports.models import LostReport  # noqa: F401
from app.modules.matching.models import MatchCandidate  # noqa: F401
from app.shared.audit import AuditLog  # noqa: F401
