import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimResult,
    IdempotencyClaimState,
    IdempotencyRepository,
    IdempotencyScope,
    IdempotencyStatus,
)


@dataclass
class _Record:
    record_id: str
    owner_token: str
    scope: IdempotencyScope
    request_fingerprint: str
    status: IdempotencyStatus
    response_snapshot: dict[str, object] | None
    business_result_reference: dict[str, object] | None
    error_code: str | None
    recovery_strategy: str | None
    recovery_attempts: int
    max_recovery_attempts: int
    recovery_metadata: dict[str, object] | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class InMemoryIdempotencyRepository(IdempotencyRepository):
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str, str], _Record] = {}
        self._locks: dict[tuple[str, str, str, str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def claim(
        self,
        scope: IdempotencyScope,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IdempotencyClaimResult:
        key = self._key(scope)
        async with self._lock_for(key):
            now = datetime.now(UTC)
            record = self._records.get(key)
            if record is None or (
                record.status == IdempotencyStatus.PROCESSING and record.expires_at <= now
            ):
                record_id = f"idem_{uuid4().hex}"
                owner_token = uuid4().hex
                self._records[key] = _Record(
                    record_id=record_id,
                    owner_token=owner_token,
                    scope=scope,
                    request_fingerprint=request_fingerprint,
                    status=IdempotencyStatus.PROCESSING,
                    response_snapshot=None,
                    business_result_reference=None,
                    error_code=None,
                    recovery_strategy=None,
                    recovery_attempts=0,
                    max_recovery_attempts=3,
                    recovery_metadata=None,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                )
                return IdempotencyClaimResult(IdempotencyClaimState.CLAIMED, record_id, owner_token)
            if record.request_fingerprint != request_fingerprint:
                return IdempotencyClaimResult(
                    IdempotencyClaimState.FINGERPRINT_CONFLICT, record.record_id
                )
            if record.status == IdempotencyStatus.PROCESSING:
                return IdempotencyClaimResult(IdempotencyClaimState.IN_PROGRESS, record.record_id)
            if record.status == IdempotencyStatus.SUCCEEDED:
                return IdempotencyClaimResult(
                    IdempotencyClaimState.REPLAY_SUCCEEDED,
                    record.record_id,
                    None,
                    response_snapshot=record.response_snapshot,
                )
            if record.status == IdempotencyStatus.RECOVERY_REQUIRED:
                return IdempotencyClaimResult(
                    IdempotencyClaimState.RECOVERY_REQUIRED,
                    record.record_id,
                    error_code=record.error_code,
                )
            previous_error = record.error_code
            record.owner_token = uuid4().hex
            record.status = IdempotencyStatus.PROCESSING
            record.error_code = None
            return IdempotencyClaimResult(
                IdempotencyClaimState.RETRY_FAILED,
                record.record_id,
                record.owner_token,
                error_code=previous_error,
            )

    async def mark_succeeded(
        self,
        record_id: str,
        owner_token: str,
        response_snapshot: dict[str, object],
    ) -> None:
        record = self._record_by_id(record_id)
        if (
            record is None
            or record.owner_token != owner_token
            or record.status != IdempotencyStatus.PROCESSING
        ):
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.SUCCEEDED
            record.response_snapshot = response_snapshot
            record.error_code = None
            record.updated_at = datetime.now(UTC)

    async def mark_failed(self, record_id: str, owner_token: str, error_code: str) -> None:
        record = self._record_by_id(record_id)
        if (
            record is None
            or record.owner_token != owner_token
            or record.status != IdempotencyStatus.PROCESSING
        ):
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.FAILED
            record.error_code = error_code
            record.updated_at = datetime.now(UTC)

    async def mark_recovery_required(
        self,
        record_id: str,
        owner_token: str,
        *,
        business_result_reference: dict[str, object],
        recovery_strategy: str,
        recovery_metadata: dict[str, object],
        error_code: str,
        max_recovery_attempts: int,
    ) -> None:
        record = self._record_by_id(record_id)
        if record is None or record.owner_token != owner_token:
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.RECOVERY_REQUIRED
            record.business_result_reference = business_result_reference
            record.recovery_strategy = recovery_strategy
            record.recovery_metadata = recovery_metadata
            record.max_recovery_attempts = max_recovery_attempts
            record.error_code = error_code
            record.updated_at = datetime.now(UTC)

    async def mark_recovery_succeeded(
        self,
        record_id: str,
        response_snapshot: dict[str, object],
        *,
        recovery_metadata: dict[str, object],
    ) -> None:
        record = self._record_by_id(record_id)
        if record is None:
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.SUCCEEDED
            record.response_snapshot = response_snapshot
            record.recovery_metadata = recovery_metadata
            record.error_code = None
            record.updated_at = datetime.now(UTC)

    async def mark_recovery_failed(
        self,
        record_id: str,
        *,
        error_code: str,
        recovery_metadata: dict[str, object],
    ) -> None:
        record = self._record_by_id(record_id)
        if record is None:
            return
        async with self._lock_for(self._key(record.scope)):
            record.recovery_attempts += 1
            record.error_code = error_code
            record.recovery_metadata = recovery_metadata
            record.updated_at = datetime.now(UTC)

    async def list_recovery_required(self, limit: int) -> list[dict[str, object]]:
        rows = [
            record
            for record in self._records.values()
            if record.status == IdempotencyStatus.RECOVERY_REQUIRED
        ]
        return [
            {
                "id": record.record_id,
                "tenant_id": record.scope.tenant_id,
                "biz_domain": record.scope.biz_domain,
                "operation": record.scope.operation.value,
                "target": record.scope.target.value,
                "idempotency_key": record.scope.idempotency_key,
                "business_result_reference": record.business_result_reference,
                "recovery_strategy": record.recovery_strategy,
                "recovery_attempts": record.recovery_attempts,
                "max_recovery_attempts": record.max_recovery_attempts,
                "error_code": record.error_code,
            }
            for record in rows[:limit]
        ]

    async def health(self) -> dict[str, str]:
        return {"status": "ok", "backend": "in_memory"}

    def _lock_for(self, key: tuple[str, str, str, str, str]) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _record_by_id(self, record_id: str) -> _Record | None:
        return next(
            (record for record in self._records.values() if record.record_id == record_id), None
        )

    @staticmethod
    def _key(scope: IdempotencyScope) -> tuple[str, str, str, str, str]:
        return (
            scope.tenant_id,
            scope.biz_domain,
            scope.operation.value,
            scope.target.value,
            scope.idempotency_key,
        )
