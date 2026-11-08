"""Hashing helpers.

Proposal NFR1: passwords, codes, session tokens and the device key are only
stored as hashes, never in plain text.

- Passwords: Argon2 (slow on purpose, with salt).
- Short codes (6 digits): HMAC-SHA256 with SECRET_KEY. Without the secret a
  stolen database does not help to guess the codes.
- Long random tokens and the device key: SHA-256 is enough, because they are
  long and random.
"""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from backend import config

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def hash_code(code: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    """Long random token, e.g. for the finder's deposit session."""
    return secrets.token_urlsafe(32)


def new_numeric_code(length: int = config.CODE_LENGTH) -> str:
    """Code for the locker keypad (only digits)."""
    return "".join(secrets.choice("0123456789") for _ in range(length))
