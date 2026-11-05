"""Order endpoints, written with relative imports."""

from fastapi import APIRouter

from ...repos.repository_factory import AllRepositories
from ...schema import order
from ...services.order_services.order_service import OrderService

router = APIRouter(prefix="/orders")


@router.get("/{order_id}")
async def get_order(order_id: int) -> order.OrderOut:
    return OrderService(AllRepositories()).get(order_id)
