from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class AuditOutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AuditEventType(StrEnum):
    ACCESS = "ACCESS"
    CHANGE = "CHANGE"


@dataclass(frozen=True)
class AuditOutboxEvent:
    event_id: str
    tenant_id: str
    biz_domain: str
    request_id: str
    trace_id: str
    actor_id: str
    event_type: AuditEventType
    target: str | None
    logical_resource_type: str
    logical_resource_name: str
    resource_id: str | None
    operation: str
    audit_payload: dict[str, object]
    payload_digest: str
    max_attempts: int


@dataclass(frozen=True)
class AuditOutboxRecord:
    id: str
    event_id: str
    event_type: AuditEventType
    audit_payload: dict[str, object]
    attempts: int
    max_attempts: int


class AuditOutboxRepository(Protocol):
    async def enqueue(self, event: AuditOutboxEvent) -> None: ...

    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lock_timeout_seconds: int,
    ) -> list[AuditOutboxRecord]: ...

    async def mark_succeeded(self, record_id: str, worker_id: str) -> None: ...

    async def mark_retry(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
        next_retry_at: datetime,
    ) -> None: ...

    async def mark_failed(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
    ) -> None: ...

    async def health(self) -> dict[str, str]: ...
