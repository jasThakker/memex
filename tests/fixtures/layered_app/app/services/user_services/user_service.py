"""Business logic for users."""

from app._base import BaseService
from app.schema.user import UserOut


class UserService(BaseService):
    """Reads users through the injected repositories."""

    def get(self, user_id: int) -> UserOut:
        user = self.repos.users.get_one(user_id)
        return UserOut(id=user.id, name=user.name)
