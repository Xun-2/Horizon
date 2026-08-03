"""PushPlus ClawBot delivery with final-state verification."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
import time
from typing import Literal

import httpx

from ..url_security import safe_request, validate_http_url


class PushPlusProtocolError(RuntimeError):
    """Raised when PushPlus returns an invalid or unsuccessful API payload."""


class PushPlusDeliveryState(str, Enum):
    ACCEPTED = "accepted"
    INACTIVE = "inactive"
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    API_FAILURE = "api_failure"


@dataclass(frozen=True)
class PushPlusDeliveryReport:
    state: PushPlusDeliveryState
    short_code: str | None = None
    detail: str | None = None

    @property
    def delivered(self) -> bool:
        return self.state == PushPlusDeliveryState.DELIVERED


RequestCallable = Callable[..., Awaitable[httpx.Response]]
SleepCallable = Callable[[float], Awaitable[None]]


class PushPlusClawBotClient:
    OPEN_API_ROOT = "https://www.pushplus.plus"

    def __init__(
        self,
        endpoint: str,
        user_token: str,
        secret_key: str | None,
        *,
        confirmation: Literal["accepted", "delivered"] = "delivered",
        status_timeout_seconds: int = 90,
        poll_interval_seconds: float = 2.0,
        request: RequestCallable = safe_request,
        sleep: SleepCallable = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        if not user_token:
            raise ValueError("PushPlus user token is required")
        if confirmation == "delivered" and not secret_key:
            raise ValueError("PushPlus secretKey is required for delivered confirmation")
        self._endpoint = validate_http_url(endpoint)
        self._user_token = user_token
        self._confirmation = confirmation
        self._secret_key = secret_key or ""
        self._status_timeout_seconds = status_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._request = request
        self._sleep = sleep
        self._monotonic = monotonic
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._access_key: str | None = None
        self._access_key_expires_at = 0.0

    def __repr__(self) -> str:
        return f"PushPlusClawBotClient(endpoint={self._endpoint!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _redact(self, value: str) -> str:
        redacted = value
        secrets = [self._user_token, self._secret_key, self._access_key or ""]
        for secret in sorted(
            (item for item in secrets if item), key=len, reverse=True
        ):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted

    def _payload(self, response: httpx.Response) -> dict:
        if not 200 <= response.status_code < 300:
            raise PushPlusProtocolError(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PushPlusProtocolError("PushPlus response is not JSON") from exc
        if not isinstance(payload, dict) or payload.get("code") != 200:
            message = (
                payload.get("msg") if isinstance(payload, dict) else "invalid payload"
            )
            raise PushPlusProtocolError(self._redact(str(message)))
        return payload

    async def _get_access_key(self) -> str:
        response = await self._request(
            self._client,
            "POST",
            f"{self.OPEN_API_ROOT}/api/common/openApi/getAccessKey",
            json={"token": self._user_token, "secretKey": self._secret_key},
        )
        payload = self._payload(response)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("accessKey"), str):
            raise PushPlusProtocolError("AccessKey response is invalid")
        access_key = data["accessKey"].strip()
        if not access_key:
            raise PushPlusProtocolError("AccessKey response is invalid")
        try:
            expires_in = int(data.get("expiresIn", 0))
        except (TypeError, ValueError) as exc:
            raise PushPlusProtocolError("AccessKey expiry is invalid") from exc
        if expires_in <= 0:
            raise PushPlusProtocolError("AccessKey expiry is invalid")
        self._access_key = access_key
        self._access_key_expires_at = self._monotonic() + expires_in
        return self._access_key

    async def _open_api_get(self, path: str, **kwargs) -> dict:
        if (
            self._access_key is None
            or self._access_key_expires_at - self._monotonic() <= 300
        ):
            await self._get_access_key()
        response = await self._request(
            self._client,
            "GET",
            f"{self.OPEN_API_ROOT}{path}",
            headers={"access-key": self._access_key},
            **kwargs,
        )
        return self._payload(response)

    async def check_binding(self) -> bool:
        payload = await self._open_api_get("/api/open/clawBot/botInfo")
        data = payload.get("data")
        return isinstance(data, dict) and data.get("haveContextToken") in {1, "1"}

    async def _delivery_status(self, short_code: str) -> tuple[int, str]:
        payload = await self._open_api_get(
            "/api/open/message/sendMessageResult",
            params={"shortCode": short_code},
        )
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("status") not in {0, 1, 2, 3}:
            raise PushPlusProtocolError("Delivery status response is invalid")
        return int(data["status"]), str(data.get("errorMessage") or "")

    async def _send_message(self, title: str, content: str) -> str:
        response = await self._request(
            self._client,
            "POST",
            self._endpoint,
            json={
                "token": self._user_token,
                "channel": "clawbot",
                "title": title,
                "content": content,
                "template": "txt",
            },
        )
        payload = self._payload(response)
        receipt = payload.get("data")
        if not isinstance(receipt, str) or not receipt.strip():
            raise PushPlusProtocolError("PushPlus response has no message receipt")
        return receipt.strip()

    async def send_and_wait(
        self,
        title: str,
        content: str,
    ) -> PushPlusDeliveryReport:
        short_code: str | None = None
        try:
            if self._confirmation == "delivered" and not await self.check_binding():
                return PushPlusDeliveryReport(
                    PushPlusDeliveryState.INACTIVE,
                    detail="ClawBot has no active conversation token",
                )
            short_code = await self._send_message(title, content)
            if self._confirmation == "accepted":
                return PushPlusDeliveryReport(
                    PushPlusDeliveryState.ACCEPTED,
                    short_code=short_code,
                )
            deadline = self._monotonic() + self._status_timeout_seconds
            while True:
                status, error_message = await self._delivery_status(short_code)
                if status == 2:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.DELIVERED,
                        short_code=short_code,
                    )
                if status == 3:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.FAILED,
                        short_code=short_code,
                        detail=self._redact(
                            error_message or "PushPlus reported failure"
                        ),
                    )
                if self._monotonic() >= deadline:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.TIMED_OUT,
                        short_code=short_code,
                        detail="Timed out waiting for final ClawBot delivery",
                    )
                await self._sleep(self._poll_interval_seconds)
        except Exception as exc:
            return PushPlusDeliveryReport(
                PushPlusDeliveryState.API_FAILURE,
                short_code=short_code,
                detail=self._redact(f"{type(exc).__name__}: {exc}"),
            )
