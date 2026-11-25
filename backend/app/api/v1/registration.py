"""Public employee self-registration endpoints.

UNAUTHENTICATED by design — the whole point is onboarding people who
have no account yet. Defence-in-depth lives on the endpoint itself:
strict per-IP rate limits (brute-forcing a 32^12 code space needs far
more attempts than this allows), server-side organization resolution,
and no authentication artifacts are ever returned.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.schemas.v1.registration import (
    DepartmentOption,
    RegistrationSubmitRequest,
    RegistrationSubmitResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.services.registration import RegistrationService

router = APIRouter(prefix="/registration", tags=["registration"])


@router.post(
    "/verify-code",
    response_model=VerifyCodeResponse,
    dependencies=[
        Depends(rate_limit("reg_verify_code", limit=10, window_seconds=60)),
    ],
)
async def verify_code(
    payload: VerifyCodeRequest,
    session: AsyncSession = Depends(get_db),
):
    """Check a 12-char organization code — returns the organization and
    property name on success so the app can confirm "you're joining X at
    Y" before submit, plus the property's active departments so the
    form can offer a real dropdown instead of free text."""
    valid, org_name, prop_name, departments = await RegistrationService(
        session
    ).verify_code(payload.code)
    return VerifyCodeResponse(
        valid=valid,
        organization_name=org_name,
        property_name=prop_name,
        departments=[
            DepartmentOption(uid=str(d.id), name=d.name)
            for d in departments
        ],
    )


@router.post(
    "",
    response_model=RegistrationSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        # Two stacked windows — a burst limit AND a slow-drip cap, so a
        # patient attacker still can't grind codes or usernames.
        Depends(rate_limit("reg_submit", limit=5, window_seconds=60)),
        Depends(rate_limit("reg_submit_hourly", limit=15, window_seconds=3600)),
    ],
)
async def submit_registration(
    payload: RegistrationSubmitRequest,
    session: AsyncSession = Depends(get_db),
):
    """Create a PENDING registration request. Never creates a user,
    never issues tokens — approval happens in the Super Admin app."""
    req, org_name, prop_name = await RegistrationService(session).submit(
        payload
    )
    return RegistrationSubmitResponse(
        request_uid=str(req.id),
        status=req.status,
        organization_name=org_name,
        property_name=prop_name,
    )
