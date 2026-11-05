"""Data access for orders."""

from app.db.models import Order


class OrderRepository:
    def get_one(self, order_id: int) -> Order:
        return Order(id=order_id)
