"""Employee API v1 router."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    attendance,
    location,
    maintenance,
    media,
    notifications,
    resources,
    tasks,
)

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(attendance.router)
api_router.include_router(maintenance.router)
api_router.include_router(resources.router)
api_router.include_router(media.router)
api_router.include_router(notifications.router)
api_router.include_router(location.router)
