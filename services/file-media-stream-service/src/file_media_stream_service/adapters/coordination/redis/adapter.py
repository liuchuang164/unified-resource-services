import asyncio
import hashlib
import secrets
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.application.ports.media_provider import StreamLease
from file_media_stream_service.application.ports.protocols import IdempotencyStore
from file_media_stream_service.domain.exceptions import (
    QuotaExceeded,
    ReplayDetected,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Lease:
    key: str
    owner_token: str
    fencing_token: int


class RedisCoordination:
    RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """
    RENEW_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('pexpire', KEYS[1], ARGV[2])
    end
    return 0
    """

    def __init__(self, client: Redis, lease_ttl_seconds: int = 30) -> None:
        self.client = client
        self.lease_ttl_ms = lease_ttl_seconds * 1000

    def idempotency_key(self, scope: tuple[str, ...]) -> str:
        tenant, domain, caller, operation, key = scope
        return "fms:idem:" + ":".join(
            _digest(value) for value in (tenant, domain, caller, operation, key)
        )

    async def acquire(self, key: str, ttl_ms: int | None = None) -> Lease | None:
        owner = secrets.token_urlsafe(24)
        fence = int(await self.client.incr(f"{key}:fence"))
        acquired = await self.client.set(key, owner, nx=True, px=ttl_ms or self.lease_ttl_ms)
        return Lease(key, owner, fence) if acquired else None

    async def renew(self, lease: Lease, ttl_ms: int | None = None) -> bool:
        result = await cast(
            Awaitable[Any],
            self.client.eval(
                self.RENEW_SCRIPT,
                1,
                lease.key,
                lease.owner_token,
                str(ttl_ms or self.lease_ttl_ms),
            ),
        )
        return bool(result)

    async def release(self, lease: Lease) -> bool:
        return bool(
            await cast(
                Awaitable[Any],
                self.client.eval(self.RELEASE_SCRIPT, 1, lease.key, lease.owner_token),
            )
        )

    async def set_stream_lease(
        self, tenant_id: str, biz_domain: str, session_id: str, owner: str
    ) -> bool:
        key = "fms:stream-lease:" + ":".join(
            _digest(value) for value in (tenant_id, biz_domain, session_id)
        )
        return bool(await self.client.set(key, owner, nx=True, px=self.lease_ttl_ms))

    async def acquire_stream_lease(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamLease | None:
        key = self._stream_key(tenant_id, biz_domain, session_id)
        fencing_token = int(await self.client.incr(f"{key}:fence"))
        acquired = await self.client.set(key, str(fencing_token), nx=True, px=self.lease_ttl_ms)
        if not acquired:
            return None
        return StreamLease(tenant_id, biz_domain, session_id, fencing_token)

    async def heartbeat_stream(self, lease: StreamLease) -> bool:
        result = await cast(
            Awaitable[Any],
            self.client.eval(
                self.RENEW_SCRIPT,
                1,
                self._stream_key(lease.tenant_id, lease.biz_domain, lease.session_id),
                str(lease.fencing_token),
                str(self.lease_ttl_ms),
            ),
        )
        return bool(result)

    async def release_stream(self, lease: StreamLease) -> bool:
        result = await cast(
            Awaitable[Any],
            self.client.eval(
                self.RELEASE_SCRIPT,
                1,
                self._stream_key(lease.tenant_id, lease.biz_domain, lease.session_id),
                str(lease.fencing_token),
            ),
        )
        return bool(result)

    @staticmethod
    def _stream_key(tenant_id: str, biz_domain: str, session_id: str) -> str:
        scope = ":".join(_digest(value) for value in (tenant_id, biz_domain, session_id))
        return f"fms:stream:{scope}:lease"

    async def health(self) -> bool:
        try:
            return bool(await self.client.ping())
        except RedisError:
            return False

    async def check(self) -> bool:
        return await self.health()


class RedisReplayProtector:
    def __init__(self, client: Redis, ttl_seconds: int = 300) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds

    async def check_and_record(self, context: RequestContext) -> None:
        if context.caller_type == "agent" and not context.nonce:
            raise ReplayDetected("Agent calls require a nonce")
        if not context.nonce:
            return
        key = "fms:replay:" + ":".join(
            _digest(value)
            for value in (context.tenant_id, context.biz_domain, context.nonce)
        )
        if not await self.client.set(key, "1", nx=True, ex=self.ttl_seconds):
            raise ReplayDetected("Request nonce has already been used")


class RedisQuotaChecker:
    def __init__(self, client: Redis, limit: int = 1000, window_seconds: int = 60) -> None:
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds

    async def check(self, context: RequestContext, operation: str) -> None:
        window = int(time.time()) // self.window_seconds
        scope = ":".join(
            _digest(value) for value in (context.tenant_id, context.biz_domain, operation)
        )
        key = f"fms:quota:{scope}:{window}"
        pipeline = self.client.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, self.window_seconds + 1)
        count, _ = await pipeline.execute()
        if int(count) > self.limit:
            raise QuotaExceeded("Quota exceeded")


class RedisCoordinatedIdempotencyStore:
    """Redis execution lease with PostgreSQL as the durable fact source."""

    def __init__(
        self,
        coordination: RedisCoordination,
        delegate: IdempotencyStore,
        *,
        wait_timeout_seconds: float = 5,
    ) -> None:
        self.coordination = coordination
        self.delegate = delegate
        self.wait_timeout_seconds = wait_timeout_seconds
        self._leases: dict[tuple[str, ...], Lease] = {}

    async def reserve(
        self, scope: tuple[str, ...], request_hash: str
    ) -> tuple[str, dict[str, Any] | None]:
        lease = await self.coordination.acquire(self.coordination.idempotency_key(scope))
        if lease is None:
            return ("WAIT", None)
        try:
            decision = await self.delegate.reserve(scope, request_hash)
        except Exception:
            await self.coordination.release(lease)
            raise
        if decision[0] == "OWNER":
            self._leases[scope] = lease
        else:
            await self.coordination.release(lease)
        return decision

    async def wait(self, scope: tuple[str, ...]) -> None:
        key = self.coordination.idempotency_key(scope)
        deadline = time.monotonic() + self.wait_timeout_seconds
        while time.monotonic() < deadline:
            if not await self.coordination.client.exists(key):
                return
            await asyncio.sleep(0.05)

    async def complete(
        self, scope: tuple[str, ...], request_hash: str, result: dict[str, Any]
    ) -> None:
        await self.delegate.complete(scope, request_hash, result)
        await self._release(scope)

    async def fail(self, scope: tuple[str, ...]) -> None:
        await self.delegate.fail(scope)
        await self._release(scope)

    async def _release(self, scope: tuple[str, ...]) -> None:
        lease = self._leases.pop(scope, None)
        if lease is not None:
            await self.coordination.release(lease)
