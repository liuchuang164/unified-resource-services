from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from redis.asyncio import Redis

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    mapping_from,
)
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext
from data_control_service.infrastructure.observability.metrics import metrics_registry
from data_control_service.infrastructure.redis.error_mapper import RedisErrorMapper
from data_control_service.infrastructure.redis.key_builder import RedisKeyBuilder
from data_control_service.infrastructure.redis.scripts import COMPARE_AND_DELETE_SCRIPT
from data_control_service.infrastructure.redis.serializer import RedisValueSerializer


@dataclass
class _CacheEntry:
    payload: str
    value_type: str
    expires_at: datetime


@dataclass
class _LockEntry:
    token: str
    expires_at: datetime


class RedisPayloadValidator:
    _forbidden_keys = {
        "redis_key",
        "physical_key",
        "command",
        "raw_command",
        "pattern",
        "script",
        "lua",
        "eval",
        "evalsha",
        "keys",
        "scan",
        "flushdb",
        "flushall",
        "config",
        "module",
        "connection_string",
        "redis_url",
        "host",
        "port",
        "password",
    }

    @classmethod
    def logical_key(cls, command: AdapterCommand, data: dict[str, Any]) -> str:
        cls.reject_forbidden(data)
        logical_key = str(
            data.get("logical_key") or command.validated_payload.get("resource_id") or ""
        )
        if not logical_key:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_key is required")
        return logical_key

    @classmethod
    def reject_forbidden(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in cls._forbidden_keys:
                    raise DataControlError(
                        "REQUEST_SCHEMA_INVALID", "raw Redis access is forbidden"
                    )
                cls.reject_forbidden(item)
        elif isinstance(value, list):
            for item in value:
                cls.reject_forbidden(item)


class RedisMapping:
    def __init__(self, command: AdapterCommand, settings: Settings) -> None:
        mapping = mapping_from(command)
        physical = mapping.physical_mapping
        self.resource_name = str(physical.get("resource_name") or mapping.definition.logical_name)
        self.key_prefix = str(physical.get("key_prefix") or settings.redis_key_prefix)
        self.value_type = str(physical.get("value_type") or "JSON")
        self.default_ttl_seconds = int(
            physical.get("default_ttl_seconds") or settings.redis_default_ttl_seconds
        )
        self.max_ttl_seconds = min(
            int(physical.get("max_ttl_seconds") or settings.redis_max_ttl_seconds),
            settings.redis_max_ttl_seconds,
        )
        self.lock_default_ttl_seconds = int(
            physical.get("lock_default_ttl_seconds") or settings.redis_lock_default_ttl_seconds
        )
        self.lock_max_ttl_seconds = min(
            int(physical.get("lock_max_ttl_seconds") or settings.redis_lock_max_ttl_seconds),
            settings.redis_lock_max_ttl_seconds,
        )
        self.max_value_bytes = min(
            int(physical.get("max_value_bytes") or settings.redis_max_value_bytes),
            settings.redis_max_value_bytes,
        )
        self.allow_permanent_keys = bool(physical.get("allow_permanent_keys", False))

    def ttl(self, data: dict[str, Any]) -> int:
        raw = data.get("ttl_seconds", self.default_ttl_seconds)
        if raw is None:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "permanent Redis keys are disabled")
        ttl = int(raw)
        if ttl <= 0 or ttl > self.max_ttl_seconds:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "ttl_seconds is invalid")
        return ttl

    def lock_ttl(self, data: dict[str, Any]) -> int:
        ttl = int(data.get("ttl_seconds") or self.lock_default_ttl_seconds)
        if ttl <= 0 or ttl > self.lock_max_ttl_seconds:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "lock ttl_seconds is invalid")
        return ttl


class InMemoryRedisAdapter(DataAdapter):
    name = "redis"
    target = DataTarget.REDIS

    def __init__(self, max_ttl_seconds: int = 86_400) -> None:
        self._values: dict[str, _CacheEntry] = {}
        self._locks: dict[str, _LockEntry] = {}
        self._settings = Settings(redis_max_ttl_seconds=max_ttl_seconds)
        self._key_builder = RedisKeyBuilder(global_prefix=self._settings.redis_key_prefix)
        self._serializer = RedisValueSerializer(
            max_value_bytes=self._settings.redis_max_value_bytes
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.EXISTS,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.LOCK,
                    Operation.UNLOCK,
                }
            ),
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=False,
            timeout_ms=1000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        data = dict(command.validated_payload.get("data", {}))
        mapping = RedisMapping(command, self._settings)
        logical_key = RedisPayloadValidator.logical_key(command, data)
        key = self._cache_key(command, mapping, logical_key)
        now = datetime.now(UTC)
        self._expire_if_needed(key, now)
        if command.operation == Operation.UPSERT:
            return self._upsert(command, mapping, data, logical_key, key, now)
        if command.operation == Operation.GET:
            entry = self._values.get(key)
            if entry is None:
                metrics_registry.increment("redis_cache_miss_total")
                raise DataControlError("RESOURCE_NOT_FOUND")
            metrics_registry.increment("redis_cache_hit_total")
            return AdapterResult(
                status="OK",
                data={
                    "logical_key": logical_key,
                    "value": self._serializer.deserialize(
                        entry.payload, value_type=entry.value_type
                    ),
                },
                affected_count=1,
            )
        if command.operation == Operation.EXISTS:
            exists = key in self._values
            metrics_registry.increment(
                "redis_cache_hit_total" if exists else "redis_cache_miss_total"
            )
            return AdapterResult(
                status="OK",
                data={"logical_key": logical_key, "exists": exists},
                affected_count=int(exists),
            )
        if command.operation == Operation.DELETE:
            existed = self._values.pop(key, None) is not None
            return AdapterResult(
                status="OK",
                data={"logical_key": logical_key, "deleted": existed},
                affected_count=int(existed),
            )
        if command.operation == Operation.LOCK:
            return self._lock(command, mapping, data, logical_key, now)
        if command.operation == Operation.UNLOCK:
            return self._unlock(command, mapping, data, logical_key, now)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    def _upsert(
        self,
        command: AdapterCommand,
        mapping: RedisMapping,
        data: dict[str, Any],
        logical_key: str,
        key: str,
        now: datetime,
    ) -> AdapterResult:
        if data.get("only_if_absent") and data.get("only_if_present"):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "NX and XX are mutually exclusive")
        if data.get("only_if_absent") and key in self._values:
            raise DataControlError("DATA_CONFLICT")
        if data.get("only_if_present") and key not in self._values:
            raise DataControlError("RESOURCE_NOT_FOUND")
        serialized = self._serializer.serialize(
            data.get("value"),
            value_type=mapping.value_type,
            max_value_bytes=mapping.max_value_bytes,
        )
        ttl = mapping.ttl(data)
        self._values[key] = _CacheEntry(
            serialized.payload, serialized.value_type, now + timedelta(seconds=ttl)
        )
        return AdapterResult(
            status="OK",
            data={
                "logical_key": logical_key,
                "ttl_seconds": ttl,
                "value_digest_bytes": serialized.size_bytes,
            },
            affected_count=1,
        )

    def _lock(
        self,
        command: AdapterCommand,
        mapping: RedisMapping,
        data: dict[str, Any],
        logical_key: str,
        now: datetime,
    ) -> AdapterResult:
        token = self._token(data)
        ttl = mapping.lock_ttl(data)
        key = self._lock_key(command, mapping, logical_key)
        existing = self._locks.get(key)
        if existing and existing.expires_at > now:
            metrics_registry.increment("redis_lock_not_acquired_total")
            raise DataControlError("LOCK_NOT_ACQUIRED")
        self._locks[key] = _LockEntry(token, now + timedelta(seconds=ttl))
        metrics_registry.increment("redis_lock_acquired_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_key": logical_key,
                "locked": True,
                "lock_token": token,
                "ttl_seconds": ttl,
            },
            affected_count=1,
        )

    def _unlock(
        self,
        command: AdapterCommand,
        mapping: RedisMapping,
        data: dict[str, Any],
        logical_key: str,
        now: datetime,
    ) -> AdapterResult:
        token = self._token(data)
        key = self._lock_key(command, mapping, logical_key)
        existing = self._locks.get(key)
        if existing is None or existing.expires_at <= now:
            self._locks.pop(key, None)
            return AdapterResult(
                status="OK", data={"logical_key": logical_key, "unlocked": False}, affected_count=0
            )
        if existing.token != token:
            metrics_registry.increment("redis_unlock_token_mismatch_total")
            raise DataControlError("LOCK_TOKEN_MISMATCH")
        self._locks.pop(key)
        metrics_registry.increment("redis_unlock_success_total")
        return AdapterResult(
            status="OK", data={"logical_key": logical_key, "unlocked": True}, affected_count=1
        )

    def _cache_key(self, command: AdapterCommand, mapping: RedisMapping, logical_key: str) -> str:
        tenant_id, biz_domain = command.scope
        return self._key_builder.cache_key(
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            resource_name=mapping.resource_name,
            logical_key=logical_key,
            key_prefix=mapping.key_prefix,
        )

    def _lock_key(self, command: AdapterCommand, mapping: RedisMapping, logical_key: str) -> str:
        tenant_id, biz_domain = command.scope
        return self._key_builder.lock_key(
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            resource_name=mapping.resource_name,
            logical_key=logical_key,
            key_prefix=mapping.key_prefix,
        )

    def _expire_if_needed(self, key: str, now: datetime) -> None:
        entry = self._values.get(key)
        if entry and entry.expires_at <= now:
            self._values.pop(key, None)
            metrics_registry.increment("redis_key_expired_total")

    @staticmethod
    def _token(data: dict[str, Any]) -> str:
        token = str(data.get("lock_token") or data.get("token") or "")
        if len(token) < 16 or len(token) > 256 or any(ord(ch) < 33 for ch in token):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "lock token is invalid")
        return token


class RedisAsyncioAdapter(InMemoryRedisAdapter):
    def __init__(self, client: Redis, settings: Settings) -> None:
        super().__init__(settings.redis_max_ttl_seconds)
        self._client = client
        self._settings = settings
        self._key_builder = RedisKeyBuilder(global_prefix=settings.redis_key_prefix)
        self._serializer = RedisValueSerializer(max_value_bytes=settings.redis_max_value_bytes)

    def capabilities(self) -> AdapterCapabilities:
        base = super().capabilities()
        return AdapterCapabilities(
            operations=base.operations,
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=False,
            timeout_ms=int(self._settings.redis_socket_timeout_seconds * 1000),
            required=self._settings.redis_adapter_required,
        )

    async def health(self) -> AdapterHealth:
        try:
            await self._client.ping()
            return AdapterHealth(
                status="UP",
                details={"adapter": self.name, "mode": "redis"},
                required=self._settings.redis_adapter_required,
            )
        except Exception:
            return AdapterHealth(
                status="DOWN",
                details={"adapter": self.name, "mode": "redis"},
                required=self._settings.redis_adapter_required,
            )

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        started = perf_counter()
        try:
            result = await self._execute(command)
            metrics_registry.increment("redis_operation_total")
            metrics_registry.observe("redis_operation_latency_seconds", perf_counter() - started)
            return result
        except Exception as exc:
            error = RedisErrorMapper.to_error(exc)
            metrics_registry.increment("redis_operation_failure_total")
            raise error from exc

    async def _execute(self, command: AdapterCommand) -> AdapterResult:
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        data = dict(command.validated_payload.get("data", {}))
        mapping = RedisMapping(command, self._settings)
        logical_key = RedisPayloadValidator.logical_key(command, data)
        key = self._cache_key(command, mapping, logical_key)
        if command.operation == Operation.UPSERT:
            return await self._redis_upsert(mapping, data, logical_key, key)
        if command.operation == Operation.GET:
            payload = await self._client.get(key)
            if payload is None:
                metrics_registry.increment("redis_cache_miss_total")
                raise DataControlError("RESOURCE_NOT_FOUND")
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            metrics_registry.increment("redis_cache_hit_total")
            return AdapterResult(
                status="OK",
                data={
                    "logical_key": logical_key,
                    "value": self._serializer.deserialize(payload, value_type=mapping.value_type),
                },
                affected_count=1,
            )
        if command.operation == Operation.EXISTS:
            exists = bool(await self._client.exists(key))
            metrics_registry.increment(
                "redis_cache_hit_total" if exists else "redis_cache_miss_total"
            )
            return AdapterResult(
                status="OK",
                data={"logical_key": logical_key, "exists": exists},
                affected_count=int(exists),
            )
        if command.operation == Operation.DELETE:
            deleted = int(await self._client.delete(key))
            return AdapterResult(
                status="OK",
                data={"logical_key": logical_key, "deleted": bool(deleted)},
                affected_count=deleted,
            )
        if command.operation == Operation.LOCK:
            return await self._redis_lock(command, mapping, data, logical_key)
        if command.operation == Operation.UNLOCK:
            return await self._redis_unlock(command, mapping, data, logical_key)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    async def _redis_upsert(
        self, mapping: RedisMapping, data: dict[str, Any], logical_key: str, key: str
    ) -> AdapterResult:
        if data.get("only_if_absent") and data.get("only_if_present"):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "NX and XX are mutually exclusive")
        serialized = self._serializer.serialize(
            data.get("value"),
            value_type=mapping.value_type,
            max_value_bytes=mapping.max_value_bytes,
        )
        ttl = mapping.ttl(data)
        ok = await self._client.set(
            key,
            serialized.payload,
            ex=ttl,
            nx=bool(data.get("only_if_absent")),
            xx=bool(data.get("only_if_present")),
        )
        if not ok:
            raise DataControlError(
                "DATA_CONFLICT" if data.get("only_if_absent") else "RESOURCE_NOT_FOUND"
            )
        return AdapterResult(
            status="OK",
            data={
                "logical_key": logical_key,
                "ttl_seconds": ttl,
                "value_digest_bytes": serialized.size_bytes,
            },
            affected_count=1,
        )

    async def _redis_lock(
        self, command: AdapterCommand, mapping: RedisMapping, data: dict[str, Any], logical_key: str
    ) -> AdapterResult:
        token = self._token(data)
        ttl = mapping.lock_ttl(data)
        key = self._lock_key(command, mapping, logical_key)
        ok = await self._client.set(key, token, px=ttl * 1000, nx=True)
        if not ok:
            metrics_registry.increment("redis_lock_not_acquired_total")
            raise DataControlError("LOCK_NOT_ACQUIRED")
        metrics_registry.increment("redis_lock_acquired_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_key": logical_key,
                "locked": True,
                "lock_token": token,
                "ttl_seconds": ttl,
            },
            affected_count=1,
        )

    async def _redis_unlock(
        self, command: AdapterCommand, mapping: RedisMapping, data: dict[str, Any], logical_key: str
    ) -> AdapterResult:
        token = self._token(data)
        key = self._lock_key(command, mapping, logical_key)
        result = int(await self._client.eval(COMPARE_AND_DELETE_SCRIPT, 1, key, token))
        if result == 1:
            metrics_registry.increment("redis_unlock_success_total")
            return AdapterResult(
                status="OK", data={"logical_key": logical_key, "unlocked": True}, affected_count=1
            )
        exists = bool(await self._client.exists(key))
        if exists:
            metrics_registry.increment("redis_unlock_token_mismatch_total")
            raise DataControlError("LOCK_TOKEN_MISMATCH")
        return AdapterResult(
            status="OK", data={"logical_key": logical_key, "unlocked": False}, affected_count=0
        )
