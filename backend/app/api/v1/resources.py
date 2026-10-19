"""Employee-visible resource hierarchy endpoints."""

import hashlib
import json

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.repositories.workspace import WorkspaceRepository
from app.schemas.v1.resources.resource import zone_out

router = APIRouter(tags=["resources"])


@router.get("/zones")
async def list_zones(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await WorkspaceRepository(session).list_zones(user)
    result["items"] = [zone_out(zone) for zone in result["items"]]
    # Weak ETag — 304 short-circuits the 60s zone-name revalidation the
    # client does. Still executes the query (one indexed list read);
    # saving the round trip entirely is what /bootstrap's scope cache is
    # for — ETag saves the transfer + parse on every unchanged poll.
    etag = 'W/"' + hashlib.sha256(
        json.dumps(jsonable_encoder(result), sort_keys=True).encode()
    ).hexdigest()[:24] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    response.headers["ETag"] = etag
    return result
