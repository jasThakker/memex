"""API schema for orders."""

from pydantic import BaseModel


class OrderOut(BaseModel):
    id: int
    user_id: int
