"""Data access for users."""

from app.db.models import User


class UserRepository:
    def get_one(self, user_id: int) -> User:
        return User(id=user_id)
