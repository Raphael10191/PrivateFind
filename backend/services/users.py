"""User accounts (support for work package 6.1).

Zohidjon builds login, sessions/JWT and the e-mail confirmation. These are
only the database functions he can call.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.database.models import User, UserRole
from backend.security import hash_password, verify_password
from backend.services.audit import log_action


class UserExistsError(Exception):
    pass


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: UserRole = UserRole.OWNER,
) -> User:
    username = username.strip()
    email = email.strip().lower()
    existing = db.scalar(
        select(User).where(or_(User.username == username, User.email == email))
    )
    if existing:
        raise UserExistsError("Username or e-mail is already used.")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()  # gives user.user_id
    log_action(db, "user_created", "user", user.user_id, user_id=user.user_id)
    return user


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.strip()))


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Returns the user if username and password are correct, otherwise None."""
    user = get_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
