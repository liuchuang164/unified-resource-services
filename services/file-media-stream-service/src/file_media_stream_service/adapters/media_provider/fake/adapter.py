import hashlib
from datetime import datetime

from file_media_stream_service.adapters.media_provider.common import ProtocolAdapter
from file_media_stream_service.adapters.media_server import InMemoryMediaServer
from file_media_stream_service.application.ports.media_provider import (
    MediaEndpoint,
    MediaStreamStatus,
)


class FakeMediaProvider:
    provider_type = "fake"

    def __init__(self, legacy_media_server: InMemoryMediaServer | None = None) -> None:
        self._protocols = ProtocolAdapter()
        self.sessions: dict[str, MediaStreamStatus] = {}
        self.endpoints: dict[str, MediaEndpoint] = {}
        self.available = True
        self.fail_create = False
        self._legacy_media_server = legacy_media_server
        self._fencing: dict[str, int] = {}

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
        if not self.available or self.fail_create:
            raise RuntimeError("Media provider unavailable")
        route = self._protocols.resolve(protocol)
        digest = hashlib.sha256(f"{tenant_id}:{biz_domain}:{session_id}".encode()).hexdigest()[:24]
        server_id = f"fake_{digest}"
        endpoint = MediaEndpoint(
            provider_type=self.provider_type,
            media_server_session_id=server_id,
            stream_key=f"stream_{digest}",
            endpoint_reference=f"fake-media://{server_id}",
            input_protocol=route.input_protocol,
            output_protocol=route.output_protocol,
        )
        self.endpoints[server_id] = endpoint
        self.sessions[server_id] = MediaStreamStatus(True, False, None)
        self._fencing[server_id] = fencing_token
        if self._legacy_media_server is not None:
            self._legacy_media_server.sessions[endpoint.endpoint_reference] = True
            self._legacy_media_server.sessions[server_id] = True
        return endpoint

    async def start_stream(self, media_server_session_id: str, fencing_token: int) -> None:
        self._verify_fencing(media_server_session_id, fencing_token)
        status = self.sessions.get(media_server_session_id)
        if status is None:
            raise RuntimeError("Media session does not exist")
        self.sessions[media_server_session_id] = MediaStreamStatus(
            True, True, datetime.now().astimezone()
        )

    async def stop_stream(self, media_server_session_id: str, fencing_token: int) -> None:
        self._verify_fencing(media_server_session_id, fencing_token)
        endpoint = self.endpoints.get(media_server_session_id)
        if endpoint is not None and self._legacy_media_server is not None:
            self._legacy_media_server.sessions[endpoint.endpoint_reference] = False
            self._legacy_media_server.sessions[media_server_session_id] = False
        self.sessions.pop(media_server_session_id, None)
        self.endpoints.pop(media_server_session_id, None)
        self._fencing.pop(media_server_session_id, None)

    async def get_stream_status(
        self, media_server_session_id: str, fencing_token: int
    ) -> MediaStreamStatus:
        if media_server_session_id in self._fencing:
            self._verify_fencing(media_server_session_id, fencing_token)
        return self.sessions.get(media_server_session_id, MediaStreamStatus(False, False))

    async def heartbeat(self, media_server_session_id: str) -> None:
        status = self.sessions.get(media_server_session_id)
        if status is None:
            raise RuntimeError("Media session does not exist")
        self.sessions[media_server_session_id] = MediaStreamStatus(
            True, status.connected, datetime.now().astimezone()
        )

    async def health_check(self) -> bool:
        return self.available

    def _verify_fencing(self, media_server_session_id: str, fencing_token: int) -> None:
        current = self._fencing.get(media_server_session_id)
        if current is None or fencing_token < current:
            raise RuntimeError("Stale media provider fencing token")
        if fencing_token > current:
            self._fencing[media_server_session_id] = fencing_token
