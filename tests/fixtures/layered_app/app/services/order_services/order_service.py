"""Business logic for orders."""

from app._base.service import BaseService
from app.schema.order import OrderOut


class OrderService(BaseService):
    """Reads orders through the injected repositories."""

    def get(self, order_id: int) -> OrderOut:
        order = self.repos.orders.get_one(order_id)
        return OrderOut(id=order.id, user_id=order.user_id)
