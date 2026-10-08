"""Employee session and self-profile endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.v1.auth.session import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    TokenRefreshResponse,
    UpdateProfileRequest,
    company_to_out,
    user_to_out,
)
from app.services.auth import AuthService, EmailAlreadyExists

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(rate_limit("login", limit=10, window_seconds=60))])
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db)):
    return await AuthService(session).login(payload.identifier, payload.password)


@router.post("/refresh", response_model=TokenRefreshResponse, dependencies=[Depends(rate_limit("refresh", limit=30, window_seconds=60))])
async def refresh(payload: RefreshRequest, session: AsyncSession = Depends(get_db)):
    return TokenRefreshResponse(access_token=await AuthService(session).refresh(payload.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, session: AsyncSession = Depends(get_db)):
    await AuthService(session).logout(payload.refresh_token)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)):
    return MeResponse(user=user_to_out(user), company=company_to_out(user.company))


@router.patch("/me", response_model=None)
async def update_me(payload: UpdateProfileRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    service = AuthService(session)
    if payload.email and payload.email != user.email and await service.users.get_by_email(payload.email):
        raise EmailAlreadyExists()
    await service.users.update_profile(user, name=payload.name, phone_number=payload.phone, email=payload.email)
    await session.commit()
    return user_to_out(user)
