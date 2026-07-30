from datetime import UTC, datetime, timedelta

import pytest

from file_media_stream_service.adapters.media_provider.common import ProtocolAdapter
from file_media_stream_service.domain.entities import StreamSession
from file_media_stream_service.domain.enums import (
    StreamConnectionState,
    StreamSessionStatus,
)
from file_media_stream_service.domain.exceptions import InvalidStateTransition


def session() -> StreamSession:
    now = datetime.now(UTC)
    return StreamSession(
        session_id="session-unit",
        tenant_id="tenant",
        biz_domain="legal",
        caller_id="caller",
        protocol="WEBRTC",
        direction="INGRESS",
        status=StreamSessionStatus.READY,
        lease_expires_at=now + timedelta(minutes=5),
        endpoint_reference="opaque",
        created_at=now,
        updated_at=now,
    )


def test_protocol_adapter_keeps_protocol_specific_routing_out_of_domain() -> None:
    adapter = ProtocolAdapter()
    assert adapter.resolve("WEBRTC").output_protocol == "WEBRTC"
    assert adapter.resolve("RTMP").output_protocol == "HLS"
    assert adapter.resolve("WS_AUDIO").input_protocol == "WS_AUDIO"
    with pytest.raises(ValueError):
        adapter.resolve("UNKNOWN")


def test_stream_connection_lifecycle_is_backward_compatible() -> None:
    value = session()
    heartbeat = datetime.now(UTC)
    value.connected(heartbeat)
    assert value.status is StreamSessionStatus.ACTIVE
    assert value.connection_state is StreamConnectionState.CONNECTED
    assert value.last_heartbeat_at == heartbeat
    value.disconnected(heartbeat)
    assert value.connection_state is StreamConnectionState.DISCONNECTED
    value.close()
    assert value.status is StreamSessionStatus.CLOSED
    with pytest.raises(InvalidStateTransition):
        value.connected(heartbeat)
