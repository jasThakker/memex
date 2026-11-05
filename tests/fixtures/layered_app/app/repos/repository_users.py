"""Data access for users."""

from app.db.models import User


class UserRepository:
    def get_one(self, user_id: int) -> User:
        return User(id=user_id)

    def get_name(self, user_id: int) -> str:
        return self.get_one(user_id).name
