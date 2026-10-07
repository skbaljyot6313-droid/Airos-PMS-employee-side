"""Employee-visible resource hierarchy endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.repositories.workspace import WorkspaceRepository
from app.schemas.v1.resources.resource import zone_out

router = APIRouter(tags=["resources"])


@router.get("/zones")
async def list_zones(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    result = await WorkspaceRepository(session).list_zones(user)
    result["items"] = [zone_out(zone) for zone in result["items"]]
    return result
