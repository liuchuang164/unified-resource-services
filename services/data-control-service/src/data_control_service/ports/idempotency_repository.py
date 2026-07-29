from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from data_control_service.contracts.enums import DataTarget, Operation


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IdempotencyClaimState(StrEnum):
    CLAIMED = "CLAIMED"
    REPLAY_SUCCEEDED = "REPLAY_SUCCEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"
    RETRY_FAILED = "RETRY_FAILED"


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

    async def health(self) -> dict[str, str]: ...
