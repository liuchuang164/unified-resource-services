import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
)

from file_media_stream_service.domain.entities import (
    AuditEvent,
    FileResource,
    FileResourceVersion,
    FileUploadSession,
    ProcessingJob,
    StreamEvent,
    StreamSession,
)
from file_media_stream_service.domain.enums import (
    FileResourceStatus,
    ProcessingJobStatus,
    StreamConnectionState,
    StreamSessionStatus,
    UploadSessionStatus,
)
from file_media_stream_service.domain.exceptions import IdempotencyConflict

from ..models import (
    AuditEventRow,
    FileResourceRow,
    FileResourceVersionRow,
    FileUploadSessionRow,
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
                current_version_id=value.current_version_id,
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
            row.current_version_id,
        )

    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None:
        await self.sessions().execute(
            delete(FileResourceRow).where(
                FileResourceRow.tenant_id == tenant_id,
                FileResourceRow.biz_domain == biz_domain,
                FileResourceRow.resource_id == resource_id,
            )
        )

    async def save(self, value: FileResource) -> None:
        row = await self.sessions().scalar(
            select(FileResourceRow).where(
                FileResourceRow.tenant_id == value.tenant_id,
                FileResourceRow.biz_domain == value.biz_domain,
                FileResourceRow.resource_id == value.resource_id,
            )
        )
        if row is None:
            await self.add(value)
            return
        row.size_bytes = value.size_bytes
        row.sha256 = value.sha256
        row.status = value.status.value
        row.version = value.version
        row.updated_at = value.updated_at
        row.object_key = value.object_key
        row.mime_type = value.mime_type
        row.current_version_id = value.current_version_id
        await self.sessions().flush()


class PostgresFileVersionRepository:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, value: FileResourceVersion) -> None:
        self.sessions().add(
            FileResourceVersionRow(
                version_id=value.version_id,
                resource_id=value.resource_id,
                tenant_id=value.tenant_id,
                biz_domain=value.biz_domain,
                version=value.version,
                object_key=value.object_key,
                size_bytes=value.size_bytes,
                checksum=value.checksum,
                mime_type=value.mime_type,
                status=value.status.value,
                created_at=value.created_at,
            )
        )
        await self.sessions().flush()

    async def list_by_scope_and_resource(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> list[FileResourceVersion]:
        rows = (
            await self.sessions().scalars(
                select(FileResourceVersionRow)
                .where(
                    FileResourceVersionRow.tenant_id == tenant_id,
                    FileResourceVersionRow.biz_domain == biz_domain,
                    FileResourceVersionRow.resource_id == resource_id,
                )
                .order_by(FileResourceVersionRow.version)
            )
        ).all()
        return [
            FileResourceVersion(
                row.version_id,
                row.resource_id,
                row.tenant_id,
                row.biz_domain,
                row.version,
                row.object_key,
                row.size_bytes,
                row.checksum,
                FileResourceStatus(row.status),
                row.created_at,
                row.mime_type,
            )
            for row in rows
        ]

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, version_id: str
    ) -> FileResourceVersion | None:
        row = await self.sessions().scalar(
            select(FileResourceVersionRow).where(
                FileResourceVersionRow.tenant_id == tenant_id,
                FileResourceVersionRow.biz_domain == biz_domain,
                FileResourceVersionRow.version_id == version_id,
            )
        )
        return None if row is None else self._entity(row)

    async def save(self, value: FileResourceVersion) -> None:
        row = await self.sessions().scalar(
            select(FileResourceVersionRow).where(
                FileResourceVersionRow.tenant_id == value.tenant_id,
                FileResourceVersionRow.biz_domain == value.biz_domain,
                FileResourceVersionRow.version_id == value.version_id,
            )
        )
        if row is None:
            await self.add(value)
            return
        row.checksum = value.checksum
        row.mime_type = value.mime_type
        row.status = value.status.value
        await self.sessions().flush()

    @staticmethod
    def _entity(row: FileResourceVersionRow) -> FileResourceVersion:
        return FileResourceVersion(
            row.version_id,
            row.resource_id,
            row.tenant_id,
            row.biz_domain,
            row.version,
            row.object_key,
            row.size_bytes,
            row.checksum,
            FileResourceStatus(row.status),
            row.created_at,
            row.mime_type,
        )


class PostgresFileUploadSessionRepository:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, value: FileUploadSession) -> None:
        self.sessions().add(
            FileUploadSessionRow(
                upload_id=value.upload_id,
                resource_id=value.resource_id,
                tenant_id=value.tenant_id,
                biz_domain=value.biz_domain,
                provider_upload_id=value.provider_upload_id,
                upload_reference=value.upload_reference,
                expires_at=value.expires_at,
                completed=value.completed,
                aborted=value.aborted,
                status=value.status.value,
                total_parts=value.total_parts,
                uploaded_parts=list(value.uploaded_parts),
                version_id=value.version_id,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
        )
        await self.sessions().flush()

    async def save(self, value: FileUploadSession) -> None:
        row = await self.sessions().scalar(
            select(FileUploadSessionRow).where(
                FileUploadSessionRow.tenant_id == value.tenant_id,
                FileUploadSessionRow.biz_domain == value.biz_domain,
                FileUploadSessionRow.upload_id == value.upload_id,
            )
        )
        if row is None:
            await self.add(value)
            return
        row.completed = value.completed
        row.aborted = value.aborted
        row.status = value.status.value
        row.total_parts = value.total_parts
        row.uploaded_parts = list(value.uploaded_parts)
        row.version_id = value.version_id
        row.updated_at = value.updated_at
        await self.sessions().flush()

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, upload_id: str
    ) -> FileUploadSession | None:
        row = await self.sessions().scalar(
            select(FileUploadSessionRow)
            .where(
                FileUploadSessionRow.tenant_id == tenant_id,
                FileUploadSessionRow.biz_domain == biz_domain,
                FileUploadSessionRow.upload_id == upload_id,
            )
            .with_for_update()
        )
        return (
            None
            if row is None
            else FileUploadSession(
                row.upload_id,
                row.resource_id,
                row.tenant_id,
                row.biz_domain,
                row.provider_upload_id,
                row.upload_reference,
                row.expires_at,
                row.completed,
                row.aborted,
                UploadSessionStatus(row.status),
                row.total_parts,
                tuple(row.uploaded_parts),
                row.version_id,
                row.created_at,
                row.updated_at,
            )
        )

    async def list_by_scope_and_resource(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> list[FileUploadSession]:
        rows = (
            await self.sessions().scalars(
                select(FileUploadSessionRow)
                .where(
                    FileUploadSessionRow.tenant_id == tenant_id,
                    FileUploadSessionRow.biz_domain == biz_domain,
                    FileUploadSessionRow.resource_id == resource_id,
                )
                .with_for_update()
            )
        ).all()
        return [self._entity(row) for row in rows]

    @staticmethod
    def _entity(row: FileUploadSessionRow) -> FileUploadSession:
        return FileUploadSession(
            row.upload_id,
            row.resource_id,
            row.tenant_id,
            row.biz_domain,
            row.provider_upload_id,
            row.upload_reference,
            row.expires_at,
            row.completed,
            row.aborted,
            UploadSessionStatus(row.status),
            row.total_parts,
            tuple(row.uploaded_parts),
            row.version_id,
            row.created_at,
            row.updated_at,
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
                        [
                            StreamSessionStatus.CREATING.value,
                            StreamSessionStatus.READY.value,
                            StreamSessionStatus.ACTIVE.value,
                        ]
                    ),
                )
            )
        ).all()
        return [self._entity(row) for row in rows]

    async def list_recovery_scopes(self) -> list[tuple[str, str]]:
        rows = (
            await self.sessions().execute(
                select(StreamSessionRow.tenant_id, StreamSessionRow.biz_domain)
                .where(
                    StreamSessionRow.status.in_(
                        [
                            StreamSessionStatus.CREATING.value,
                            StreamSessionStatus.READY.value,
                            StreamSessionStatus.ACTIVE.value,
                        ]
                    )
                )
                .distinct()
            )
        ).all()
        return [(tenant_id, biz_domain) for tenant_id, biz_domain in rows]

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
                offset=event.offset,
                length=event.length,
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

    async def list_pending(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        rows = (
            await self.sessions().scalars(
                select(ReconciliationRecordRow).where(
                    ReconciliationRecordRow.kind == kind,
                    ReconciliationRecordRow.status == "PENDING",
                )
            )
        ).all()
        return [(row.key, dict(row.payload)) for row in rows]


class PostgresIndependentReconciliationStore:
    """Writes recovery truth in a transaction isolated from request failures."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.factory = async_sessionmaker(engine, expire_on_commit=False)

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
        async with self.factory() as session, session.begin():
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ReconciliationRecordRow.key],
                    set_={"payload": serialized, "status": "PENDING", "updated_at": now},
                )
            )

    async def resolve(self, key: str, tenant_id: str, biz_domain: str) -> None:
        async with self.factory() as session, session.begin():
            await session.execute(
                delete(ReconciliationRecordRow).where(
                    ReconciliationRecordRow.key == key,
                    ReconciliationRecordRow.tenant_id == tenant_id,
                    ReconciliationRecordRow.biz_domain == biz_domain,
                )
            )

    async def list_pending(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        async with self.factory() as session:
            rows = (
                await session.scalars(
                    select(ReconciliationRecordRow).where(
                        ReconciliationRecordRow.kind == kind,
                        ReconciliationRecordRow.status == "PENDING",
                    )
                )
            ).all()
            return [(row.key, dict(row.payload)) for row in rows]


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
        if row.expires_at <= now:
            row.status = "RUNNING"
            row.response_snapshot = None
            row.updated_at = now
            row.expires_at = now + timedelta(seconds=self.ttl_seconds)
            await session.flush()
            self._events.setdefault(scope, asyncio.Event())
            return ("OWNER", None)
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
        await self.sessions().commit()
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
