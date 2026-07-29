from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper
from data_control_service.infrastructure.persistence.models.audit_outbox import AuditOutboxModel
from data_control_service.ports.audit_outbox_repository import (
    AuditEventType,
    AuditOutboxEvent,
    AuditOutboxRecord,
    AuditOutboxRepository,
    AuditOutboxStatus,
)


class SQLAlchemyAuditOutboxRepository(AuditOutboxRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(self, event: AuditOutboxEvent) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            session.add(
                AuditOutboxModel(
                    id=f"audit_outbox_{uuid4().hex}",
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    biz_domain=event.biz_domain,
                    request_id=event.request_id,
                    trace_id=event.trace_id,
                    actor_id=event.actor_id,
                    event_type=event.event_type.value,
                    target=event.target,
                    logical_resource_type=event.logical_resource_type,
                    logical_resource_name=event.logical_resource_name,
                    resource_id=event.resource_id,
                    operation=event.operation,
                    audit_payload=event.audit_payload,
                    payload_digest=event.payload_digest,
                    status=AuditOutboxStatus.PENDING.value,
                    attempts=0,
                    max_attempts=event.max_attempts,
                    next_retry_at=now,
                    locked_by=None,
                    locked_at=None,
                    last_error_code=None,
                    last_error_message_digest=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
            except Exception as exc:
                raise PostgreSQLErrorMapper.to_error(exc) from exc

    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lock_timeout_seconds: int,
    ) -> list[AuditOutboxRecord]:
        now = datetime.now(UTC)
        expired_lock = now - timedelta(seconds=lock_timeout_seconds)
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(AuditOutboxModel)
                    .where(
                        AuditOutboxModel.status.in_(
                            [
                                AuditOutboxStatus.PENDING.value,
                                AuditOutboxStatus.PROCESSING.value,
                            ]
                        ),
                        AuditOutboxModel.next_retry_at <= now,
                        AuditOutboxModel.attempts < AuditOutboxModel.max_attempts,
                        or_(
                            AuditOutboxModel.status == AuditOutboxStatus.PENDING.value,
                            AuditOutboxModel.locked_at.is_(None),
                            AuditOutboxModel.locked_at < expired_lock,
                        ),
                    )
                    .order_by(AuditOutboxModel.next_retry_at, AuditOutboxModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars().all())
                for row in rows:
                    row.status = AuditOutboxStatus.PROCESSING.value
                    row.locked_by = worker_id
                    row.locked_at = now
                    row.attempts += 1
                    row.updated_at = now
                return [
                    AuditOutboxRecord(
                        id=row.id,
                        event_id=row.event_id,
                        event_type=AuditEventType(row.event_type),
                        audit_payload=row.audit_payload,
                        attempts=row.attempts,
                        max_attempts=row.max_attempts,
                    )
                    for row in rows
                ]

    async def mark_succeeded(self, record_id: str, worker_id: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(AuditOutboxModel, record_id, with_for_update=True)
                if row is None or row.locked_by != worker_id:
                    return
                row.status = AuditOutboxStatus.SUCCEEDED.value
                row.locked_by = None
                row.locked_at = None
                row.updated_at = now
                row.completed_at = now

    async def mark_retry(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
        next_retry_at: datetime,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(AuditOutboxModel, record_id, with_for_update=True)
                if row is None or row.locked_by != worker_id:
                    return
                row.status = AuditOutboxStatus.PENDING.value
                row.locked_by = None
                row.locked_at = None
                row.last_error_code = error_code
                row.last_error_message_digest = error_message_digest
                row.next_retry_at = next_retry_at
                row.updated_at = now

    async def mark_failed(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(AuditOutboxModel, record_id, with_for_update=True)
                if row is None or row.locked_by != worker_id:
                    return
                row.status = AuditOutboxStatus.FAILED.value
                row.locked_by = None
                row.locked_at = None
                row.last_error_code = error_code
                row.last_error_message_digest = error_message_digest
                row.updated_at = now

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().filter(AuditOutboxModel.status == AuditOutboxStatus.PENDING.value),
                    func.count().filter(AuditOutboxModel.status == AuditOutboxStatus.FAILED.value),
                )
            )
            pending, failed = result.one()
        return {
            "status": "ok",
            "backend": "postgresql",
            "pending": str(pending),
            "failed": str(failed),
        }
