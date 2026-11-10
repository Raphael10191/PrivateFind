"""FastAPI dependencies other modules use to protect their routes."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.modules.identity import service
from app.modules.identity.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: SessionDep) -> User:
    user_id = request.session.get("user_id")
    user = await service.get_user(session, user_id) if user_id else None
    if user is None:
        raise AppError(401, "not_authenticated", "Please log in.")
    return user


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise AppError(403, "forbidden", "Administrator access required.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
