"""One object that holds every repository."""

from app.repos.repository_orders import OrderRepository
from app.repos.repository_users import UserRepository


class AllRepositories:
    """Injected into services, which reach repositories as `self.repos.<name>`."""

    def __init__(self) -> None:
        self.users = UserRepository()
        self.orders = OrderRepository()
