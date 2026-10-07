"""Employee maintenance reporting and assigned-work endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_employee
from app.models.user import User
from app.schemas.v1.maintenance.ticket import MaintenanceCreateRequest, MaintenanceResolveRequest, ticket_out
from app.services.maintenance import MaintenanceService

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("")
async def list_maintenance(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    tickets = await MaintenanceService(session).list_tickets(user)
    return {"items": [ticket_out(ticket) for ticket in tickets], "total": len(tickets)}


@router.get("/eligible-locations")
async def eligible_locations(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return await MaintenanceService(session).eligible_locations(user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ticket(payload: MaintenanceCreateRequest, user: User = Depends(require_employee), session: AsyncSession = Depends(get_db)):
    return ticket_out(await MaintenanceService(session).create_ticket(user, payload))


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return ticket_out(await MaintenanceService(session).get_ticket(user, ticket_id))


@router.post("/{ticket_id}/start")
async def start_ticket(ticket_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return ticket_out(await MaintenanceService(session).start(user, ticket_id))


@router.post("/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: uuid.UUID, payload: MaintenanceResolveRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return ticket_out(await MaintenanceService(session).resolve(user, ticket_id, payload))
