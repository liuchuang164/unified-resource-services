import asyncio

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError

from file_media_stream_service.adapters.coordination.redis import (
    RedisCoordinatedIdempotencyStore,
    RedisCoordination,
    RedisQuotaChecker,
    RedisReplayProtector,
)
from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.domain.exceptions import QuotaExceeded, ReplayDetected

pytestmark = pytest.mark.production_integration
REDIS_URL = "redis://localhost:56379/15"


def context(nonce: str = "nonce") -> RequestContext:
    return RequestContext(
        request_id="req",
        trace_id="trace",
        tenant_id="tenant-a",
        biz_domain="legal",
        caller_type="agent",
        caller_id="agent-a",
        agent_id="agent-a",
        tool_call_id="tool-call-a",
        capability_token="token",
        nonce=nonce,
        idempotency_key="idem",
    )


@pytest.mark.asyncio
async def test_lease_owner_expiry_renew_replay_and_quota() -> None:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    await client.flushdb()
    coordination = RedisCoordination(client, lease_ttl_seconds=1)
    lease = await coordination.acquire("fms:test:lease", 150)
    assert lease is not None
    assert await coordination.acquire("fms:test:lease", 150) is None
    wrong = type(lease)(lease.key, "wrong-owner", lease.fencing_token)
    assert await coordination.release(wrong) is False
    assert await coordination.renew(lease, 300)
    assert await coordination.release(lease)
    assert await coordination.release(lease) is False
    expiring = await coordination.acquire("fms:test:expiry", 30)
    assert expiring is not None
    await asyncio.sleep(0.05)
    assert await coordination.acquire("fms:test:expiry", 100) is not None
    assert await coordination.set_stream_lease("tenant-a", "legal", "session-a", "owner-a")
    assert not await coordination.set_stream_lease("tenant-a", "legal", "session-a", "owner-b")
    stream_lease = await coordination.acquire_stream_lease("tenant-a", "legal", "session-phase2")
    assert stream_lease is not None
    assert await coordination.acquire_stream_lease("tenant-a", "legal", "session-phase2") is None
    assert await coordination.heartbeat_stream(stream_lease)
    stale_stream_lease = type(stream_lease)(
        stream_lease.tenant_id,
        stream_lease.biz_domain,
        stream_lease.session_id,
        stream_lease.fencing_token + 1,
    )
    assert not await coordination.release_stream(stale_stream_lease)
    assert await coordination.release_stream(stream_lease)

    replay = RedisReplayProtector(client)
    missing_nonce = context()
    object.__setattr__(missing_nonce, "nonce", None)
    with pytest.raises(ReplayDetected):
        await replay.check_and_record(missing_nonce)
    await replay.check_and_record(context())
    with pytest.raises(ReplayDetected):
        await replay.check_and_record(context())

    quota = RedisQuotaChecker(client, limit=1)
    await quota.check(context("n2"), "file.initialize_upload")
    with pytest.raises(QuotaExceeded):
        await quota.check(context("n3"), "file.initialize_upload")
    assert await coordination.check()
    await client.aclose()


class RecordingIdempotency:
    def __init__(self) -> None:
        self.decision: tuple[str, dict[str, object] | None] = ("OWNER", None)
        self.completed = False
        self.failed = False

    async def reserve(
        self, scope: tuple[str, ...], request_hash: str
    ) -> tuple[str, dict[str, object] | None]:
        return self.decision

    async def wait(self, scope: tuple[str, ...]) -> None:
        return None

    async def complete(
        self, scope: tuple[str, ...], request_hash: str, result: dict[str, object]
    ) -> None:
        self.completed = True

    async def fail(self, scope: tuple[str, ...]) -> None:
        self.failed = True


@pytest.mark.asyncio
async def test_coordinated_idempotency_owner_wait_complete_and_fail() -> None:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    await client.flushdb()
    coordination = RedisCoordination(client)
    delegate = RecordingIdempotency()
    store = RedisCoordinatedIdempotencyStore(coordination, delegate, wait_timeout_seconds=0.1)
    scope = ("tenant", "domain", "caller", "operation", "sensitive-key")
    assert await store.reserve(scope, "hash") == ("OWNER", None)
    assert await store.reserve(scope, "hash") == ("WAIT", None)
    await store.complete(scope, "hash", {"ok": True})
    assert delegate.completed
    await store.wait(scope)
    assert await store.reserve(scope, "hash") == ("OWNER", None)
    await store.fail(scope)
    assert delegate.failed
    await client.aclose()


@pytest.mark.asyncio
async def test_redis_disconnect_is_not_silently_accepted() -> None:
    client = Redis.from_url(
        "redis://localhost:1/0",
        socket_connect_timeout=0.05,
        socket_timeout=0.05,
        decode_responses=True,
    )
    coordination = RedisCoordination(client)
    assert await coordination.check() is False
    with pytest.raises(ConnectionError):
        await coordination.acquire("fms:test:offline")
    await client.aclose()
