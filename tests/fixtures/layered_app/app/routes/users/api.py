"""User endpoints."""

from fastapi import APIRouter

from app.repos.repository_factory import AllRepositories
from app.schema.user import UserOut
from app.services.user_services import UserService

router = APIRouter(prefix="/users")


@router.get("/{user_id}")
async def get_user(user_id: int) -> UserOut:
    return UserService(AllRepositories()).get(user_id)
