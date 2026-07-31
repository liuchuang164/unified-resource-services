from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from data_access_gateway.config import Settings
from data_access_gateway.errors import GatewayError


@dataclass(frozen=True)
class DownstreamResponse:
    status_code: int
    body: dict[str, Any]


class DataControlClient(Protocol):
    async def dispatch(
        self,
        request: dict[str, Any],
        capability_token: str,
    ) -> DownstreamResponse: ...

    async def ready(self) -> bool: ...

    async def close(self) -> None: ...


class HttpDataControlClient:
    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.data_control_base_url.rstrip("/"),
            timeout=settings.data_control_timeout_seconds,
        )

    async def dispatch(
        self,
        request: dict[str, Any],
        capability_token: str,
    ) -> DownstreamResponse:
        try:
            response = await self._client.post(
                "/data/dispatch",
                json=request,
                headers={
                    "Authorization": f"Bearer {capability_token}",
                    "X-Request-Id": str(request["request_id"]),
                    "X-Trace-Id": str(request["trace_id"]),
                },
            )
        except httpx.TimeoutException as exc:
            raise GatewayError("DATA_CONTROL_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise GatewayError("DATA_CONTROL_UNAVAILABLE") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError("DATA_CONTROL_RESPONSE_INVALID") from exc
        if not isinstance(body, dict) or "success" not in body or "code" not in body:
            raise GatewayError("DATA_CONTROL_RESPONSE_INVALID")
        return DownstreamResponse(response.status_code, body)

    async def ready(self) -> bool:
        try:
            response = await self._client.get("/health/ready")
            return response.status_code == 200 and response.json().get("ready") is True
        except (httpx.HTTPError, ValueError):
            return False

    async def close(self) -> None:
        await self._client.aclose()
