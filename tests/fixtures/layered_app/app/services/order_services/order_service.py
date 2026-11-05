"""Business logic for orders."""

from app._base.service import BaseService
from app.repos.repository_factory import AllRepositories
from app.schema.order import OrderOut


class OrderService(BaseService):
    """Reads orders through the injected repositories."""

    def __init__(self, repos: AllRepositories) -> None:
        super().__init__(repos)

    @classmethod
    def create(cls) -> OrderService:
        return cls(cls.default_repos())

    @staticmethod
    def default_repos() -> AllRepositories:
        return AllRepositories()

    def get(self, order_id: int) -> OrderOut:
        order = self.repos.orders.get_one(order_id)
        return OrderOut(id=order.id, user_id=order.user_id)

    def owner_name(self, order_id: int) -> str:
        """Reaches a repository method whose name is unique in the codebase."""
        return self.repos.users.get_name(self.get(order_id).user_id)
