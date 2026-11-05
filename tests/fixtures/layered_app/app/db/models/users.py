"""User table."""

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ._model_base import SqlAlchemyBase

if TYPE_CHECKING:
    from .orders import Order


class User(SqlAlchemyBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    orders: Mapped[list[Order]] = relationship("Order", back_populates="user")
