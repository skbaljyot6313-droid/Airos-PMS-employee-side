"""Centrifugo realtime endpoints — connection + subscription tokens.

    GET  /realtime/token      → short-lived Centrifugo connection JWT
    POST /realtime/subscribe  → per-channel subscription JWTs

This API mints subscription tokens for ONE channel shape only:
    priv:emp:{employee_uid} — and only when the caller's own
    `user.employee_id` matches. Property/admin channels are minted by
    the Super Admin backend; employees must never subscribe to another
    employee's channel or to property-wide data.
"""

import re
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import centrifugo
from app.core.exceptions import AppError
from app.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/realtime", tags=["realtime"])

_EMP_RE = re.compile(
    rf"^{centrifugo.PRIVATE_NS}:emp:([0-9a-f-]{{36}})$"
)


class RealtimeUnavailable(AppError):
    status_code = 503
    code = "REALTIME_UNAVAILABLE"
    message = "Real-time delivery is not configured."


class ChannelDenied(AppError):
    status_code = 403
    code = "CHANNEL_DENIED"
    message = "You are not authorized for one or more channels."


class SubscribeRequest(BaseModel):
    channels: list[str] = Field(min_length=1, max_length=20)


@router.get("/token")
async def realtime_token(user: User = Depends(get_current_user)):
    if not centrifugo.configured():
        raise RealtimeUnavailable()
    token, exp = centrifugo.connection_token(user)
    return {
        "token": token,
        "expires_at": exp,
        "ws_url": centrifugo.ws_url(),
    }


@router.post("/subscribe")
async def subscribe(
    payload: SubscribeRequest,
    user: User = Depends(get_current_user),
):
    if not centrifugo.configured():
        raise RealtimeUnavailable()
    for ch in payload.channels:
        m = _EMP_RE.match(ch)
        if m is None:
            raise ChannelDenied()
        if user.employee_id is None or user.employee_id != uuid.UUID(
            m.group(1)
        ):
            raise ChannelDenied()
    tokens = {}
    for ch in payload.channels:
        tokens[ch], exp = centrifugo.subscription_token(user, ch)
    return {"tokens": tokens, "expires_at": exp}
