import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.identity.models import User
from app.shared import audit

_hasher = PasswordHasher()


async def register(
    session: AsyncSession, email: str, password: str, display_name: str | None, role="owner"
) -> User:
    email = email.lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise AppError(409, "email_taken", "An account with this e-mail already exists.")
    user = User(
        username=f"user_{secrets.token_hex(8)}",
        email=email,
        password_hash=_hasher.hash(password),
        display_name=display_name,
        role=role,
    )
    session.add(user)
    await session.flush()
    audit.log(session, "user_registered", "user", user.id, actor_type="user", actor_id=user.id)
    await session.commit()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    try:
        if user is None:
            raise VerifyMismatchError
        _hasher.verify(user.password_hash, password)
    except VerifyMismatchError as exc:
        raise AppError(401, "invalid_credentials", "Wrong e-mail or password.") from exc
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)
