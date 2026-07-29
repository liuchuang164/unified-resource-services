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
    error_code: str | None
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
                    error_code=None,
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
        if record is None or record.owner_token != owner_token:
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.SUCCEEDED
            record.response_snapshot = response_snapshot
            record.updated_at = datetime.now(UTC)

    async def mark_failed(self, record_id: str, owner_token: str, error_code: str) -> None:
        record = self._record_by_id(record_id)
        if record is None or record.owner_token != owner_token:
            return
        async with self._lock_for(self._key(record.scope)):
            record.status = IdempotencyStatus.FAILED
            record.error_code = error_code
            record.updated_at = datetime.now(UTC)

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
