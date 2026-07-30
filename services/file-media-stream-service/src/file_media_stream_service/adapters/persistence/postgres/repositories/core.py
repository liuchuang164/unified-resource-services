import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from file_media_stream_service.domain.entities import (
    AuditEvent,
    FileResource,
    ProcessingJob,
    StreamEvent,
    StreamSession,
)
from file_media_stream_service.domain.enums import (
    FileResourceStatus,
    ProcessingJobStatus,
    StreamConnectionState,
    StreamSessionStatus,
)
from file_media_stream_service.domain.exceptions import IdempotencyConflict

from ..models import (
    AuditEventRow,
    FileResourceRow,
    IdempotencyRecordRow,
    ProcessingJobRow,
    ReconciliationRecordRow,
    StreamEventRow,
    StreamSessionRow,
)


class PostgresFileRepository:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, value: FileResource) -> None:
        self.sessions().add(
            FileResourceRow(
                resource_id=value.resource_id,
                tenant_id=value.tenant_id,
                biz_domain=value.biz_domain,
                owner_type=value.owner_type,
                owner_id=value.owner_id,
                original_filename=value.original_filename,
                normalized_filename=value.normalized_filename,
                object_key=value.object_key,
                mime_type=value.mime_type,
                size_bytes=value.size_bytes,
                sha256=value.sha256,
                status=value.status.value,
                version=value.version,
                created_by=value.created_by,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
        )
        await self.sessions().flush()

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> FileResource | None:
        row = await self.sessions().scalar(
            select(FileResourceRow).where(
                FileResourceRow.tenant_id == tenant_id,
                FileResourceRow.biz_domain == biz_domain,
                FileResourceRow.resource_id == resource_id,
            )
        )
        if row is None:
            return None
        return FileResource(
            row.resource_id,
            row.tenant_id,
            row.biz_domain,
            row.owner_type,
            row.owner_id,
            row.original_filename,
            row.normalized_filename,
            row.object_key,
            row.mime_type,
            row.size_bytes,
            row.sha256,
            FileResourceStatus(row.status),
            row.version,
            row.created_by,
            row.created_at,
            row.updated_at,
        )

    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None:
        await self.sessions().execute(
            delete(FileResourceRow).where(
                FileResourceRow.tenant_id == tenant_id,
                FileResourceRow.biz_domain == biz_domain,
                FileResourceRow.resource_id == resource_id,
            )
        )


class PostgresStreamSessionRepository:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, value: StreamSession) -> None:
        self.sessions().add(self._row(value))
        await self.sessions().flush()

    async def save(self, value: StreamSession) -> None:
        row = await self.sessions().scalar(
            select(StreamSessionRow).where(
                StreamSessionRow.tenant_id == value.tenant_id,
                StreamSessionRow.biz_domain == value.biz_domain,
                StreamSessionRow.session_id == value.session_id,
            )
        )
        if row is None:
            await self.add(value)
            return
        row.status = value.status.value
        row.lease_expires_at = value.lease_expires_at
        row.endpoint_reference = value.media_server_session_id or value.endpoint_reference
        row.provider_type = value.provider_type
        row.stream_key = ""
        row.input_protocol = value.input_protocol
        row.output_protocol = value.output_protocol
        row.endpoint = ""
        row.media_server_session_id = value.media_server_session_id
        row.last_heartbeat_at = value.last_heartbeat_at
        row.connection_state = value.connection_state.value
        row.fencing_token = value.fencing_token
        row.updated_at = value.updated_at
        await self.sessions().flush()

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamSession | None:
        row = await self.sessions().scalar(
            select(StreamSessionRow).where(
                StreamSessionRow.tenant_id == tenant_id,
                StreamSessionRow.biz_domain == biz_domain,
                StreamSessionRow.session_id == session_id,
            )
        )
        return (
            None
            if row is None
            else StreamSession(
                row.session_id,
                row.tenant_id,
                row.biz_domain,
                row.caller_id,
                row.protocol,
                row.direction,
                StreamSessionStatus(row.status),
                row.lease_expires_at,
                row.endpoint_reference,
                row.created_at,
                row.updated_at,
                row.provider_type,
                row.stream_key,
                row.input_protocol,
                row.output_protocol,
                row.endpoint,
                row.media_server_session_id,
                row.last_heartbeat_at,
                StreamConnectionState(row.connection_state),
                row.fencing_token,
            )
        )

    async def list_recoverable(self, tenant_id: str, biz_domain: str) -> list[StreamSession]:
        rows = (
            await self.sessions().scalars(
                select(StreamSessionRow).where(
                    StreamSessionRow.tenant_id == tenant_id,
                    StreamSessionRow.biz_domain == biz_domain,
                    StreamSessionRow.status.in_(
                        [StreamSessionStatus.READY.value, StreamSessionStatus.ACTIVE.value]
                    ),
                )
            )
        ).all()
        return [self._entity(row) for row in rows]

    @staticmethod
    def _entity(row: StreamSessionRow) -> StreamSession:
        return StreamSession(
            row.session_id,
            row.tenant_id,
            row.biz_domain,
            row.caller_id,
            row.protocol,
            row.direction,
            StreamSessionStatus(row.status),
            row.lease_expires_at,
            row.endpoint_reference,
            row.created_at,
            row.updated_at,
            row.provider_type,
            row.stream_key,
            row.input_protocol,
            row.output_protocol,
            row.endpoint,
            row.media_server_session_id,
            row.last_heartbeat_at,
            StreamConnectionState(row.connection_state),
            row.fencing_token,
        )

    @staticmethod
    def _row(value: StreamSession) -> StreamSessionRow:
        return StreamSessionRow(
            session_id=value.session_id,
            tenant_id=value.tenant_id,
            biz_domain=value.biz_domain,
            caller_id=value.caller_id,
            protocol=value.protocol,
            direction=value.direction,
            status=value.status.value,
            lease_expires_at=value.lease_expires_at,
            endpoint_reference=value.media_server_session_id or value.endpoint_reference,
            provider_type=value.provider_type,
            stream_key="",
            input_protocol=value.input_protocol,
            output_protocol=value.output_protocol,
            endpoint="",
            media_server_session_id=value.media_server_session_id,
            last_heartbeat_at=value.last_heartbeat_at,
            connection_state=value.connection_state.value,
            fencing_token=value.fencing_token,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class PostgresStreamEventSink:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def write_stream_event(self, event: StreamEvent) -> None:
        if set(event.metadata) - {"connection_state"}:
            raise ValueError("Stream event metadata contains forbidden fields")
        if any(len(key) > 64 or len(value) > 128 for key, value in event.metadata.items()):
            raise ValueError("Stream event metadata is too large")
        self.sessions().add(
            StreamEventRow(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                biz_domain=event.biz_domain,
                session_id=event.session_id,
                event_type=event.event_type.value,
                provider=event.provider,
                timestamp=event.timestamp,
                metadata_json=event.metadata,
            )
        )
        await self.sessions().flush()


class PostgresProcessingJobRepository:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, value: ProcessingJob) -> None:
        self.sessions().add(self._row(value))
        await self.sessions().flush()

    async def save(self, value: ProcessingJob) -> None:
        row = await self.sessions().scalar(
            select(ProcessingJobRow).where(
                ProcessingJobRow.tenant_id == value.tenant_id,
                ProcessingJobRow.biz_domain == value.biz_domain,
                ProcessingJobRow.job_id == value.job_id,
            )
        )
        if row is None:
            await self.add(value)
            return
        row.status = value.status.value
        row.output_resource_ids = list(value.output_resource_ids)
        row.attempt = value.attempt
        row.updated_at = value.updated_at
        await self.sessions().flush()

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, job_id: str
    ) -> ProcessingJob | None:
        row = await self.sessions().scalar(
            select(ProcessingJobRow).where(
                ProcessingJobRow.tenant_id == tenant_id,
                ProcessingJobRow.biz_domain == biz_domain,
                ProcessingJobRow.job_id == job_id,
            )
        )
        return (
            None
            if row is None
            else ProcessingJob(
                row.job_id,
                row.tenant_id,
                row.biz_domain,
                row.operation,
                row.input_resource_id,
                tuple(row.output_resource_ids),
                ProcessingJobStatus(row.status),
                row.processor_type,
                row.attempt,
                row.created_at,
                row.updated_at,
            )
        )

    @staticmethod
    def _row(value: ProcessingJob) -> ProcessingJobRow:
        return ProcessingJobRow(
            job_id=value.job_id,
            tenant_id=value.tenant_id,
            biz_domain=value.biz_domain,
            operation=value.operation,
            input_resource_id=value.input_resource_id,
            output_resource_ids=list(value.output_resource_ids),
            status=value.status.value,
            processor_type=value.processor_type,
            attempt=value.attempt,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class PostgresAuditSink:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def write(self, event: AuditEvent) -> None:
        self.sessions().add(
            AuditEventRow(
                audit_id=event.audit_id,
                request_id=event.request_id,
                trace_id=event.trace_id,
                tenant_id=event.tenant_id,
                biz_domain=event.biz_domain,
                caller_type=event.caller_type,
                caller_id=event.caller_id,
                operation=event.operation,
                resource_id=event.resource_id,
                session_id=event.session_id,
                job_id=event.job_id,
                decision=event.decision,
                result=event.result,
                error_code=event.error_code,
                duration_ms=event.duration_ms,
                created_at=event.created_at,
            )
        )
        await self.sessions().flush()


class PostgresReconciliationStore:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def record(self, key: str, kind: str, payload: Mapping[str, Any]) -> None:
        now = datetime.now(UTC)
        serialized = dict(payload)
        statement = insert(ReconciliationRecordRow).values(
            key=key,
            kind=kind,
            tenant_id=str(payload["tenant_id"]),
            biz_domain=str(payload["biz_domain"]),
            payload=serialized,
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        await self.sessions().execute(
            statement.on_conflict_do_update(
                index_elements=[ReconciliationRecordRow.key],
                set_={"payload": serialized, "status": "PENDING", "updated_at": now},
            )
        )

    async def resolve(self, key: str, tenant_id: str, biz_domain: str) -> None:
        await self.sessions().execute(
            delete(ReconciliationRecordRow).where(
                ReconciliationRecordRow.key == key,
                ReconciliationRecordRow.tenant_id == tenant_id,
                ReconciliationRecordRow.biz_domain == biz_domain,
            )
        )


class PostgresIdempotencyStore:
    def __init__(
        self, sessions: async_scoped_session[AsyncSession], ttl_seconds: int = 86400
    ) -> None:
        self.sessions = sessions
        self.ttl_seconds = ttl_seconds
        self._events: dict[tuple[str, ...], asyncio.Event] = {}

    async def reserve(
        self, scope: tuple[str, ...], request_hash: str
    ) -> tuple[str, dict[str, Any] | None]:
        tenant, domain, caller, operation, key = scope
        now = datetime.now(UTC)
        session = self.sessions()
        statement = (
            insert(IdempotencyRecordRow)
            .values(
                tenant_id=tenant,
                biz_domain=domain,
                caller_id=caller,
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
                status="RUNNING",
                response_snapshot=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=self.ttl_seconds),
            )
            .on_conflict_do_nothing()
            .returning(IdempotencyRecordRow.id)
        )
        created = await session.scalar(statement)
        if created is not None:
            self._events.setdefault(scope, asyncio.Event())
            return ("OWNER", None)
        row = await session.scalar(
            select(IdempotencyRecordRow).where(
                IdempotencyRecordRow.tenant_id == tenant,
                IdempotencyRecordRow.biz_domain == domain,
                IdempotencyRecordRow.caller_id == caller,
                IdempotencyRecordRow.operation == operation,
                IdempotencyRecordRow.idempotency_key == key,
            )
        )
        if row is None:
            return ("WAIT", None)
        if row.request_hash != request_hash:
            raise IdempotencyConflict("Idempotency key was used with another request")
        if row.status == "COMPLETED":
            return ("COMPLETED", row.response_snapshot)
        return ("WAIT", None)

    async def wait(self, scope: tuple[str, ...]) -> None:
        try:
            await asyncio.wait_for(self._events.setdefault(scope, asyncio.Event()).wait(), 5)
        except TimeoutError:
            return

    async def complete(
        self, scope: tuple[str, ...], request_hash: str, result: dict[str, Any]
    ) -> None:
        tenant, domain, caller, operation, key = scope
        row = await self.sessions().scalar(
            select(IdempotencyRecordRow)
            .where(
                IdempotencyRecordRow.tenant_id == tenant,
                IdempotencyRecordRow.biz_domain == domain,
                IdempotencyRecordRow.caller_id == caller,
                IdempotencyRecordRow.operation == operation,
                IdempotencyRecordRow.idempotency_key == key,
                IdempotencyRecordRow.request_hash == request_hash,
            )
            .with_for_update()
        )
        if row is None:
            raise IdempotencyConflict("Idempotency reservation is missing")
        row.status = "COMPLETED"
        row.response_snapshot = result
        row.updated_at = datetime.now(UTC)
        await self.sessions().flush()
        self._events.setdefault(scope, asyncio.Event()).set()

    async def fail(self, scope: tuple[str, ...]) -> None:
        tenant, domain, caller, operation, key = scope
        await self.sessions().execute(
            delete(IdempotencyRecordRow).where(
                IdempotencyRecordRow.tenant_id == tenant,
                IdempotencyRecordRow.biz_domain == domain,
                IdempotencyRecordRow.caller_id == caller,
                IdempotencyRecordRow.operation == operation,
                IdempotencyRecordRow.idempotency_key == key,
            )
        )
        self._events.setdefault(scope, asyncio.Event()).set()
