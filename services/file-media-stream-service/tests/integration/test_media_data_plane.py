from datetime import UTC, datetime, timedelta

import httpx
import pytest

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.media_provider import (
    FakeMediaProvider,
    GenericHttpMediaProvider,
    InMemoryStreamCoordination,
)
from file_media_stream_service.adapters.persistence import (
    InMemoryStreamSessionRepository,
)
from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.application.use_cases import StreamLifecycleService
from file_media_stream_service.bootstrap import Container
from file_media_stream_service.domain.enums import (
    StreamConnectionState,
    StreamEventType,
    StreamSessionStatus,
)


def context() -> RequestContext:
    return RequestContext(
        request_id="phase2",
        trace_id="phase2-trace",
        tenant_id="tenant-phase2",
        biz_domain="legal",
        caller_type="service",
        caller_id="service-phase2",
        idempotency_key="phase2-idem",
    )


@pytest.mark.asyncio
async def test_fake_provider_create_start_heartbeat_stop() -> None:
    provider = FakeMediaProvider()
    endpoint = await provider.create_stream_endpoint(
        "tenant", "legal", "session", "RTMP", "INGRESS", datetime.now(UTC), 7
    )
    assert endpoint.output_protocol == "HLS"
    assert not (await provider.get_stream_status(endpoint.media_server_session_id, 7)).connected
    await provider.start_stream(endpoint.media_server_session_id, 7)
    await provider.heartbeat(endpoint.media_server_session_id)
    status = await provider.get_stream_status(endpoint.media_server_session_id, 7)
    assert status.connected and status.last_heartbeat_at is not None
    await provider.stop_stream(endpoint.media_server_session_id, 7)
    assert not (await provider.get_stream_status(endpoint.media_server_session_id, 7)).exists
    assert await provider.health_check()


@pytest.mark.asyncio
async def test_full_lifecycle_and_restart_reconciliation(container: Container) -> None:
    created = await container.entry.use_cases.create_stream_session(
        context(), {"protocol": "WEBRTC", "direction": "INGRESS"}
    )
    session_id = str(created["session"]["session_id"])
    lifecycle = StreamLifecycleService(
        InMemoryStreamSessionRepository(container.state),
        container.media_provider,
        container.stream_coordination,
        container.stream_events,
        container.reconciliation,
        SystemClock(),
        UuidIdentifierFactory(),
    )
    active = await lifecycle.mark_connected("tenant-phase2", "legal", session_id)
    assert active.status is StreamSessionStatus.ACTIVE
    await container.media_provider.heartbeat(active.media_server_session_id)
    heartbeat = await lifecycle.heartbeat("tenant-phase2", "legal", session_id)
    assert heartbeat.connection_state is StreamConnectionState.CONNECTED
    assert container.stream_events.events[-1].event_type is StreamEventType.STREAM_CONNECTED

    container.media_provider.sessions.clear()
    recovered = await lifecycle.reconcile_scope("tenant-phase2", "legal")
    assert recovered[0].status is StreamSessionStatus.FAILED
    assert f"stream-restart:{session_id}" in container.reconciliation.pending


@pytest.mark.asyncio
async def test_fencing_token_rejects_stale_owner() -> None:
    coordination = InMemoryStreamCoordination()
    first = await coordination.acquire_stream_lease("tenant", "domain", "session")
    assert first is not None
    assert await coordination.acquire_stream_lease("tenant", "domain", "session") is None
    stale = type(first)("tenant", "domain", "session", first.fencing_token + 1)
    assert not await coordination.heartbeat_stream(stale)
    assert not await coordination.release_stream(stale)
    assert await coordination.release_stream(first)
    second = await coordination.acquire_stream_lease("tenant", "domain", "session")
    assert second is not None
    assert second.fencing_token > first.fencing_token


@pytest.mark.asyncio
async def test_generic_http_provider_contract_and_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/streams" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "media_server_session_id": "provider-session",
                    "stream_key": "opaque-stream",
                    "endpoint_reference": "https://media.invalid/opaque",
                    "input_protocol": "WEBRTC",
                    "output_protocol": "WEBRTC",
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "exists": True,
                    "connected": True,
                    "last_heartbeat_at": datetime.now(UTC).isoformat(),
                },
            )
        return httpx.Response(204, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GenericHttpMediaProvider(
        "https://provider.invalid", api_token="secret", client=client
    )
    endpoint = await provider.create_stream_endpoint(
        "tenant",
        "legal",
        "session",
        "WEBRTC",
        "INGRESS",
        datetime.now(UTC) + timedelta(minutes=5),
        3,
    )
    await provider.start_stream(endpoint.media_server_session_id, 3)
    status = await provider.get_stream_status(endpoint.media_server_session_id, 3)
    assert status.exists and status.connected
    await provider.stop_stream(endpoint.media_server_session_id, 3)
    assert await provider.health_check()
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_failure_persists_failed_session_and_reconciliation(
    container: Container,
) -> None:
    container.media_provider.fail_create = True
    with pytest.raises(RuntimeError, match="unavailable"):
        await container.entry.use_cases.create_stream_session(
            context(), {"protocol": "WEBRTC", "direction": "INGRESS"}
        )
    stored = next(iter(container.state.sessions.values()))
    assert stored.status is StreamSessionStatus.FAILED
    assert f"stream-provider:{stored.session_id}" in container.reconciliation.pending


@pytest.mark.asyncio
async def test_provider_success_then_database_failure_is_compensated(
    container: Container,
) -> None:
    async def fail_add(session: object) -> None:
        raise RuntimeError("database unavailable")

    container.entry.use_cases.sessions.add = fail_add  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="database unavailable"):
        await container.entry.use_cases.create_stream_session(
            context(), {"protocol": "WEBRTC", "direction": "INGRESS"}
        )
    assert container.media_provider.sessions == {}
    assert container.stream_coordination.leases == {}
    assert container.reconciliation.pending == {}


@pytest.mark.asyncio
async def test_generic_provider_timeout_is_not_swallowed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    provider = GenericHttpMediaProvider(
        "https://provider.invalid", api_token="secret", client=client
    )
    with pytest.raises(httpx.ReadTimeout):
        await provider.create_stream_endpoint(
            "tenant",
            "legal",
            "session",
            "WEBRTC",
            "INGRESS",
            datetime.now(UTC),
            1,
        )
    assert not await provider.health_check()
    await client.aclose()


@pytest.mark.asyncio
async def test_lost_lease_marks_active_session_failed(container: Container) -> None:
    created = await container.entry.use_cases.create_stream_session(
        context(), {"protocol": "WEBRTC", "direction": "INGRESS"}
    )
    session_id = str(created["session"]["session_id"])
    repository = InMemoryStreamSessionRepository(container.state)
    lifecycle = StreamLifecycleService(
        repository,
        container.media_provider,
        container.stream_coordination,
        container.stream_events,
        container.reconciliation,
        SystemClock(),
        UuidIdentifierFactory(),
    )
    session = await repository.get_by_scope_and_id("tenant-phase2", "legal", session_id)
    assert session is not None
    lease = next(iter(container.stream_coordination.leases.values()))
    await container.stream_coordination.release_stream(lease)
    with pytest.raises(RuntimeError, match="lost"):
        await lifecycle.heartbeat("tenant-phase2", "legal", session_id)
    failed = await repository.get_by_scope_and_id("tenant-phase2", "legal", session_id)
    assert failed is not None
    assert failed.status is StreamSessionStatus.FAILED
