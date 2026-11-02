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
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict,
        tag: str | None = None,
    ) -> PushResult: ...


class LogPushProvider:
    """STUB — writes the payload to the app.push log until FCM creds
    exist. Cannot detect dead tokens: invalid_tokens is always empty."""

    async def send(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict,
        tag: str | None = None,
    ) -> PushResult:
        logger.info(
            "push:stub tokens=%d title=%r body=%r data=%s tag=%s",
            len(tokens), title, body, data, tag,
        )
        return PushResult(delivered=list(tokens))


class FCMProvider:
    """Firebase Cloud Messaging HTTP v1.

    Auth = OAuth2 access token minted from the service account's
    JWT-bearer assertion (RS256 — requires 'cryptography')."""

    def __init__(self, project_id: str, credentials):
        self.project_id = project_id
        self.creds = credentials  # google.auth Credentials (ADC or SA info)

    @classmethod
    def from_settings(cls) -> "FCMProvider":
        """Credentials chain — Application Default Credentials first
        (the Cloud Run runtime service account), with an optional
        FCM_SERVICE_ACCOUNT_JSON fallback for non-GCP environments.
        No key files are required on GCP deployments."""
        if not settings.FCM_PROJECT_ID:
            raise PushUnavailable(
                "FCM provider selected but FCM_PROJECT_ID is not configured."
            )
        try:
            if settings.FCM_SERVICE_ACCOUNT_JSON:
                from google.oauth2 import service_account

                raw = settings.FCM_SERVICE_ACCOUNT_JSON.strip()
                info = (
                    json.loads(raw)
                    if raw.startswith("{")
                    else json.loads(Path(raw).read_text(encoding="utf-8"))
                )
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=[FCM_SCOPE]
                )
            else:
                import google.auth

                creds, _ = google.auth.default(scopes=[FCM_SCOPE])
        except Exception as exc:
            raise PushUnavailable(
                f"FCM credentials unavailable: {type(exc).__name__}"
            ) from exc
        return cls(settings.FCM_PROJECT_ID, creds)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        creds = self.creds
        if creds.valid and creds.token:
            return creds.token
        import asyncio

        from google.auth.transport.requests import Request

        try:
            await asyncio.to_thread(creds.refresh, Request())
        except Exception as exc:
            raise PushUnavailable(
                f"FCM credential refresh failed: {type(exc).__name__}"
            ) from exc
        return creds.token

    async def send(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict,
        tag: str | None = None,
    ) -> PushResult:
        result = PushResult()
        if not tokens:
            return result
        url = FCM_V1_URL.format(project=self.project_id)
        # FCM data payloads are string-only maps. Data-only on purpose:
        # a "notification" block lets Android display the alert itself
        # when the app is backgrounded, which bypasses the app's dedup
        # ledger and lets the work-feed poller repost dismissed items.
        # The app's messaging service posts the tray entry instead.
        str_data = {k: str(v) for k, v in (data or {}).items()}
        str_data["title"] = title
        str_data["body"] = body
        async with httpx.AsyncClient(timeout=10.0) as client:
            access = await self._access_token(client)
            for token in tokens:
                res = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access}"},
                    json={
                        "message": {
                            "token": token,
                            "data": str_data,
                            # HIGH so data messages reach a dozing/killed
                            # app — the app's service posts the tray entry.
                            "android": {"priority": "HIGH"},
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
