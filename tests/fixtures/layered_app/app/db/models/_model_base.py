"""Declarative base shared by every ORM model."""

from sqlalchemy.orm import DeclarativeBase


class SqlAlchemyBase(DeclarativeBase):
    """Subclasses a class from outside the codebase."""
