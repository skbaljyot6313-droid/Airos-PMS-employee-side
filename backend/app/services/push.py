"""Push dispatch — provider protocol + implementations.

The notification service calls ``get_push_provider().send(...)`` AFTER
persisting the row; a provider failure is logged and swallowed there —
work allocation must never fail on push.

Providers:
  * LogPushProvider — default STUB until FCM credentials exist. Logs the
    payload; cannot detect dead tokens (documented limitation — the
    invalid-token cleanup hook only activates under FCM).
  * FCMProvider — real FCM HTTP v1 send. Raises PushUnavailable unless
    project + service-account credentials are configured AND the
    'cryptography' package is importable (RS256 OAuth assertion signing).
    No delivery is ever faked: a send that can't authenticate raises.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.push")

FCM_V1_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
# FCM error statuses meaning "this registration token is dead" —
# deactivated server-side so we stop hammering them.
_DEAD_TOKEN_ERRORS = frozenset({"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"})


class PushUnavailable(Exception):
    """Provider exists but cannot deliver (missing creds / dependency)."""


@dataclass
class PushResult:
    delivered: list[str] = field(default_factory=list)
    # Registration tokens FCM reported as dead — caller deactivates them.
    invalid_tokens: list[str] = field(default_factory=list)


class PushProvider(Protocol):
    async def send(
        self, tokens: list[str], title: str, body: str, data: dict
    ) -> PushResult: ...


class LogPushProvider:
    """STUB — writes the payload to the app.push log until FCM creds
    exist. Cannot detect dead tokens: invalid_tokens is always empty."""

    async def send(
        self, tokens: list[str], title: str, body: str, data: dict
    ) -> PushResult:
        logger.info(
            "push:stub tokens=%d title=%r body=%r data=%s",
            len(tokens), title, body, data,
        )
        return PushResult(delivered=list(tokens))


class FCMProvider:
    """Firebase Cloud Messaging HTTP v1.

    Auth = OAuth2 access token minted from the service account's
    JWT-bearer assertion (RS256 — requires 'cryptography')."""

    def __init__(self, project_id: str, service_account: dict):
        self.project_id = project_id
        self.sa = service_account
        self._token: tuple[str, float] | None = None  # (access, expiry epoch)

    @classmethod
    def from_settings(cls) -> "FCMProvider":
        if not settings.FCM_PROJECT_ID or not settings.FCM_SERVICE_ACCOUNT_JSON:
            raise PushUnavailable(
                "FCM provider selected but FCM_PROJECT_ID / "
                "FCM_SERVICE_ACCOUNT_JSON are not configured."
            )
        raw = settings.FCM_SERVICE_ACCOUNT_JSON.strip()
        try:
            if raw.startswith("{"):
                sa_info = json.loads(raw)
            else:
                sa_info = json.loads(Path(raw).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PushUnavailable(f"FCM service account JSON unreadable: {exc}")
        if not sa_info.get("client_email") or not sa_info.get("private_key"):
            raise PushUnavailable("FCM service account JSON is incomplete.")
        return cls(settings.FCM_PROJECT_ID, sa_info)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token[1] - 60:
            return self._token[0]
        try:
            import jwt  # PyJWT — RS256 needs the cryptography extra
            import cryptography  # noqa: F401
        except ImportError as exc:
            raise PushUnavailable(
                "FCM OAuth signing requires the 'cryptography' package."
            ) from exc
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": self.sa["client_email"],
                "sub": self.sa["client_email"],
                "aud": GOOGLE_TOKEN_URL,
                "scope": FCM_SCOPE,
                "iat": now,
                "exp": now + 3600,
            },
            self.sa["private_key"],
            algorithm="RS256",
        )
        res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if res.status_code != 200:
            raise PushUnavailable(
                f"FCM token exchange failed ({res.status_code})."
            )
        payload = res.json()
        self._token = (
            payload["access_token"], now + int(payload.get("expires_in", 3600))
        )
        return self._token[0]

    async def send(
        self, tokens: list[str], title: str, body: str, data: dict
    ) -> PushResult:
        result = PushResult()
        if not tokens:
            return result
        url = FCM_V1_URL.format(project=self.project_id)
        # FCM data payloads are string-only maps.
        str_data = {k: str(v) for k, v in (data or {}).items()}
        async with httpx.AsyncClient(timeout=10.0) as client:
            access = await self._access_token(client)
            for token in tokens:
                res = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access}"},
                    json={
                        "message": {
                            "token": token,
                            "notification": {"title": title, "body": body},
                            "data": str_data,
                        }
                    },
                )
                if res.status_code == 200:
                    result.delivered.append(token)
                    continue
                status = ""
                try:
                    status = (
                        res.json().get("error", {})
                        .get("details", [{}])[0]
                        .get("errorCode", "")
                    ) or res.json().get("error", {}).get("status", "")
                except Exception:
                    pass
                if status in _DEAD_TOKEN_ERRORS:
                    result.invalid_tokens.append(token)
                else:
                    logger.warning(
                        "FCM send failed token=%s… status=%s http=%s",
                        token[:12], status, res.status_code,
                    )
        return result


def get_push_provider() -> PushProvider:
    """Factory on settings.PUSH_PROVIDER ('log' default, 'fcm')."""
    if (settings.PUSH_PROVIDER or "log").strip().lower() == "fcm":
        return FCMProvider.from_settings()
    return LogPushProvider()
