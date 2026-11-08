"""Shared dependencies for the API routes: database session, logged-in user, admin check, IP limit."""
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend import config
from backend.database.database import get_db
from backend.database.models import User, UserRole
from backend.services.users import get_user

__all__ = ["get_db", "get_current_user", "get_current_admin", "limit_by_ip"]


def get_current_user(
    x_user_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """TEMPORARY until login is ready (6.1, Zohidjon).

    For now the logged-in user is sent in the header "X-User-Id" (e.g. from the seed
    data). Zohidjon replaces only this function with the real session/JWT check;
    all routes that use Depends(get_current_user) then work without changes.
    """
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    user = get_user(db, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Authorization: only administrators may use the admin routes."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only for administrators.")
    return user


# IP address -> times of the requests in the last minute.
# Kept in memory: enough for our prototype with one server process.
_requests_per_ip: dict[str, list[datetime]] = {}


def limit_by_ip(request: Request) -> None:
    """Max. RATE_LIMIT_PER_MINUTE requests per IP and minute, then HTTP 429.

    The IP is only slowed down for a minute, never blocked for good (proposal 4.4).
    """
    ip = request.client.host if request.client else "unknown"
    now = datetime.now()
    one_minute_ago = now - timedelta(minutes=1)

    recent = [t for t in _requests_per_ip.get(ip, []) if t > one_minute_ago]
    if len(recent) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")
    recent.append(now)
    _requests_per_ip[ip] = recent


def reset_rate_limit() -> None:
    """Only for the tests."""
    _requests_per_ip.clear()
