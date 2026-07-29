from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    mapping_from,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass
class _CacheEntry:
    value: object
    expires_at: datetime


@dataclass
class _LockEntry:
    token: str
    expires_at: datetime


class InMemoryRedisAdapter(DataAdapter):
    name = "redis"
    target = DataTarget.REDIS

    def __init__(self, max_ttl_seconds: int = 86_400) -> None:
        self._values: dict[str, _CacheEntry] = {}
        self._locks: dict[str, _LockEntry] = {}
        self._max_ttl_seconds = max_ttl_seconds

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
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
        data = command.validated_payload.get("data", {})
        if any(key in data for key in {"redis_key", "command", "raw_command", "pattern", "script"}):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "raw Redis access is forbidden")
        logical_key = str(
            data.get("logical_key") or command.validated_payload.get("resource_id") or ""
        )
        if not logical_key or any(
            word in logical_key.upper()
            for word in {
                "KEYS",
                "SCAN",
                "EVAL",
                "FLUSHDB",
                "FLUSHALL",
                "CONFIG",
                "SCRIPT",
                "MODULE",
            }
        ):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "invalid logical key")
        key = self._key(command, logical_key)
        now = datetime.now(UTC)
        if command.operation == Operation.UPSERT:
            ttl = int(data.get("ttl_seconds", 0))
            if ttl <= 0 or ttl > self._max_ttl_seconds:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "ttl_seconds is invalid")
            self._values[key] = _CacheEntry(data.get("value"), now + timedelta(seconds=ttl))
            return AdapterResult(status="OK", data={"logical_key": logical_key}, affected_count=1)
        if command.operation == Operation.GET:
            entry = self._values.get(key)
            if entry is None or entry.expires_at <= now:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(
                status="OK",
                data={"logical_key": logical_key, "value": entry.value},
                affected_count=1,
            )
        if command.operation == Operation.DELETE:
            existed = self._values.pop(key, None) is not None
            return AdapterResult(
                status="OK", data={"deleted": existed}, affected_count=int(existed)
            )
        if command.operation == Operation.LOCK:
            token = str(data.get("token") or "")
            ttl = int(data.get("ttl_seconds", 0))
            if not token or ttl <= 0 or ttl > self._max_ttl_seconds:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "lock token and ttl are required")
            existing = self._locks.get(key)
            if existing and existing.expires_at > now:
                raise DataControlError("LOCK_CONFLICT")
            self._locks[key] = _LockEntry(token, now + timedelta(seconds=ttl))
            return AdapterResult(status="OK", data={"locked": True}, affected_count=1)
        if command.operation == Operation.UNLOCK:
            token = str(data.get("token") or "")
            existing = self._locks.get(key)
            if existing is None or existing.token != token:
                raise DataControlError("LOCK_CONFLICT")
            self._locks.pop(key)
            return AdapterResult(status="OK", data={"unlocked": True}, affected_count=1)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    @staticmethod
    def _key(command: AdapterCommand, logical_key: str) -> str:
        mapping = mapping_from(command)
        tenant_id, biz_domain = command.scope
        return f"dcs:{tenant_id}:{biz_domain}:{mapping.definition.logical_name}:{logical_key}"
