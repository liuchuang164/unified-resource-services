from datetime import datetime
from typing import Any

import httpx

from file_media_stream_service.application.ports.media_provider import (
    MediaEndpoint,
    MediaStreamStatus,
)


class GenericHttpMediaProvider:
    provider_type = "generic-http"

    def __init__(
        self,
        base_url: str,
        *,
        api_token: str,
        timeout_seconds: float = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = api_token
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def create_stream_endpoint(
        self,
        tenant_id: str,
        biz_domain: str,
        session_id: str,
        protocol: str,
        direction: str,
        lease_expires_at: datetime,
        fencing_token: int,
    ) -> MediaEndpoint:
        data = await self._request(
            "POST",
            "/v1/streams",
            {
                "tenant_id": tenant_id,
                "biz_domain": biz_domain,
                "session_id": session_id,
                "protocol": protocol,
                "direction": direction,
                "lease_expires_at": lease_expires_at.isoformat(),
                "fencing_token": fencing_token,
            },
        )
        return MediaEndpoint(
            provider_type=self.provider_type,
            media_server_session_id=str(data["media_server_session_id"]),
            stream_key=str(data["stream_key"]),
            endpoint_reference=str(data["endpoint_reference"]),
            input_protocol=str(data["input_protocol"]),
            output_protocol=str(data["output_protocol"]),
        )

    async def start_stream(self, media_server_session_id: str, fencing_token: int) -> None:
        await self._request(
            "POST",
            f"/v1/streams/{media_server_session_id}/start",
            {"fencing_token": fencing_token},
        )

    async def stop_stream(self, media_server_session_id: str, fencing_token: int) -> None:
        await self._request(
            "POST",
            f"/v1/streams/{media_server_session_id}/stop",
            {"fencing_token": fencing_token},
        )

    async def get_stream_status(
        self, media_server_session_id: str, fencing_token: int
    ) -> MediaStreamStatus:
        data = await self._request(
            "GET",
            f"/v1/streams/{media_server_session_id}",
            {"fencing_token": fencing_token},
        )
        heartbeat = data.get("last_heartbeat_at")
        return MediaStreamStatus(
            exists=bool(data["exists"]),
            connected=bool(data["connected"]),
            last_heartbeat_at=datetime.fromisoformat(str(heartbeat)) if heartbeat else None,
        )

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/health", headers=self._headers())
            return response.is_success
        except httpx.HTTPError:
            return False

    async def _request(self, method: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.request(
            method,
            f"{self._base_url}{path}",
            json=data,
            headers=self._headers(),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("Media provider response is invalid")
        return result

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
