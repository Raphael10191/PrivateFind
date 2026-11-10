"""Simon’s database enum values, shared by the domain model mappings."""

from sqlalchemy import Enum


def db_enum(*values: str) -> Enum:
    return Enum(*values, native_enum=True, validate_strings=True)
