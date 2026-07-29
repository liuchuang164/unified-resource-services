from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from data_control_service.contracts.enums import DataTarget, Operation


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class IdempotencyClaimState(StrEnum):
    CLAIMED = "CLAIMED"
    REPLAY_SUCCEEDED = "REPLAY_SUCCEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"
    RETRY_FAILED = "RETRY_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class IdempotencyScope:
    tenant_id: str
    biz_domain: str
    operation: Operation
    target: DataTarget
    idempotency_key: str


@dataclass(frozen=True)
class IdempotencyClaimResult:
    state: IdempotencyClaimState
    record_id: str
    owner_token: str | None = None
    response_snapshot: dict[str, object] | None = None
    error_code: str | None = None


class IdempotencyRepository(Protocol):
    async def claim(
        self,
        scope: IdempotencyScope,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IdempotencyClaimResult: ...

    async def mark_succeeded(
        self,
        record_id: str,
        owner_token: str,
        response_snapshot: dict[str, object],
    ) -> None: ...

    async def mark_failed(self, record_id: str, owner_token: str, error_code: str) -> None: ...

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
    ) -> None: ...

    async def mark_recovery_succeeded(
        self,
        record_id: str,
        response_snapshot: dict[str, object],
        *,
        recovery_metadata: dict[str, object],
    ) -> None: ...

    async def mark_recovery_failed(
        self,
        record_id: str,
        *,
        error_code: str,
        recovery_metadata: dict[str, object],
    ) -> None: ...

    async def list_recovery_required(self, limit: int) -> list[dict[str, object]]: ...

    async def health(self) -> dict[str, str]: ...
