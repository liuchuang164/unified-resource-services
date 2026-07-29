from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.application.audit_service import stable_digest
from data_control_service.infrastructure.persistence.models.access_audit import AccessAuditLogModel
from data_control_service.infrastructure.persistence.models.change_audit import ChangeAuditLogModel
from data_control_service.ports.audit_outbox_repository import (
    AuditEventType,
    AuditOutboxRepository,
)


class AuditOutboxProcessor:
    def __init__(
        self,
        *,
        outbox_repository: AuditOutboxRepository,
        audit_session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        batch_size: int,
        lock_timeout_seconds: int,
    ) -> None:
        self._outbox_repository = outbox_repository
        self._audit_session_factory = audit_session_factory
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lock_timeout_seconds = lock_timeout_seconds

    async def run_once(self) -> dict[str, int]:
        claimed = await self._outbox_repository.claim_batch(
            worker_id=self._worker_id,
            limit=self._batch_size,
            lock_timeout_seconds=self._lock_timeout_seconds,
        )
        processed = 0
        failed = 0
        for record in claimed:
            try:
                await self._write_formal_audit(record.event_type, record.audit_payload)
                await self._outbox_repository.mark_succeeded(record.id, self._worker_id)
                processed += 1
            except Exception as exc:
                failed += 1
                digest = stable_digest({"type": type(exc).__name__, "message": str(exc)})
                if record.attempts >= record.max_attempts:
                    await self._outbox_repository.mark_failed(
                        record.id,
                        self._worker_id,
                        error_code="AUDIT_WRITE_FAILED",
                        error_message_digest=digest,
                    )
                else:
                    await self._outbox_repository.mark_retry(
                        record.id,
                        self._worker_id,
                        error_code="AUDIT_WRITE_FAILED",
                        error_message_digest=digest,
                        next_retry_at=datetime.now(UTC) + timedelta(seconds=record.attempts),
                    )
        return {"claimed": len(claimed), "processed": processed, "failed": failed}

    async def _write_formal_audit(
        self, event_type: AuditEventType, payload: dict[str, object]
    ) -> None:
        async with self._audit_session_factory() as session:
            async with session.begin():
                if event_type == AuditEventType.ACCESS:
                    session.add(
                        AccessAuditLogModel(
                            id=f"audit_{uuid4().hex}", **payload, created_at=datetime.now(UTC)
                        )
                    )
                    return
                if event_type == AuditEventType.CHANGE:
                    session.add(
                        ChangeAuditLogModel(
                            id=f"change_{uuid4().hex}", **payload, created_at=datetime.now(UTC)
                        )
                    )
                    return
                raise ValueError(f"unknown audit event type: {event_type}")
