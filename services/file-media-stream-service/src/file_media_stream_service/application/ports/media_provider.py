from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaEndpoint:
    provider_type: str
    media_server_session_id: str
    stream_key: str
    endpoint_reference: str
    input_protocol: str
    output_protocol: str


@dataclass(frozen=True, slots=True)
class MediaStreamStatus:
    exists: bool
    connected: bool
    last_heartbeat_at: datetime | None = None


class MediaProviderPort(Protocol):
    async def create_stream_endpoint(
        self,
        tenant_id: str,
        biz_domain: str,
        session_id: str,
        protocol: str,
        direction: str,
        lease_expires_at: datetime,
        fencing_token: int,
    ) -> MediaEndpoint: ...

    async def start_stream(self, media_server_session_id: str, fencing_token: int) -> None: ...
    async def stop_stream(self, media_server_session_id: str, fencing_token: int) -> None: ...
    async def get_stream_status(
        self, media_server_session_id: str, fencing_token: int
    ) -> MediaStreamStatus: ...
    async def health_check(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class StreamLease:
    tenant_id: str
    biz_domain: str
    session_id: str
    fencing_token: int


class StreamCoordinationPort(Protocol):
    async def acquire_stream_lease(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamLease | None: ...
    async def heartbeat_stream(self, lease: StreamLease) -> bool: ...
    async def release_stream(self, lease: StreamLease) -> bool: ...
