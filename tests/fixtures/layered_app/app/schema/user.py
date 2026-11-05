"""API schema for users."""

from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    name: str
