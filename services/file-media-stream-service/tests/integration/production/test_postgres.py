import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from file_media_stream_service.adapters.persistence.postgres import (
    PostgresAuditSink,
    PostgresFileRepository,
    PostgresIdempotencyStore,
    PostgresIndependentReconciliationStore,
    PostgresProcessingJobRepository,
    PostgresReconciliationStore,
    PostgresStreamEventSink,
    PostgresStreamSessionRepository,
    create_engine,
    create_session_registry,
)
from file_media_stream_service.adapters.persistence.postgres.models import (
    AuditEventRow,
    FileResourceRow,
    ProcessingJobRow,
    ReconciliationRecordRow,
    StreamEventRow,
    StreamSessionRow,
)
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
    StreamEventType,
    StreamSessionStatus,
)

pytestmark = pytest.mark.production_integration
DATABASE_URL = "postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream"


def test_00_migration_upgrade_downgrade_upgrade() -> None:
    environment = {**os.environ, "DATABASE_URL": DATABASE_URL}
    subprocess.run([".venv/bin/alembic", "downgrade", "-1"], check=True, env=environment)
    subprocess.run([".venv/bin/alembic", "upgrade", "head"], check=True, env=environment)


def resource(resource_id: str = "res_pg") -> FileResource:
    now = datetime.now(UTC)
    return FileResource(
        resource_id=resource_id,
        tenant_id="tenant-a",
        biz_domain="legal",
        owner_type="case",
        owner_id="case-1",
        original_filename="a.txt",
        normalized_filename="a.txt",
        object_key=f"tenant-a/legal/{resource_id}/v1/a.txt",
        mime_type="text/plain",
        size_bytes=3,
        sha256=None,
        status=FileResourceStatus.PENDING_UPLOAD,
        version=1,
        created_by="svc",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_repository_scope_rollback_unique_audit_and_reconciliation() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    files = PostgresFileRepository(sessions)
    try:
        await sessions().execute(
            FileResourceRow.__table__.delete().where(FileResourceRow.resource_id.like("res_pg%"))
        )
        await sessions().execute(
            AuditEventRow.__table__.delete().where(AuditEventRow.audit_id == "audit_pg")
        )
        await sessions().execute(
            ReconciliationRecordRow.__table__.delete().where(
                ReconciliationRecordRow.key == "recon_pg"
            )
        )
        await sessions().commit()
        await files.add(resource())
        await sessions().commit()
        assert await files.get_by_scope_and_id("tenant-a", "legal", "res_pg") is not None
        assert await files.get_by_scope_and_id("tenant-b", "legal", "res_pg") is None
        assert await files.get_by_scope_and_id("tenant-a", "finance", "res_pg") is None

        await files.add(resource("res_pg_rollback"))
        await sessions().rollback()
        assert await files.get_by_scope_and_id("tenant-a", "legal", "res_pg_rollback") is None

        with pytest.raises(IntegrityError):
            await files.add(resource())
        await sessions().rollback()

        now = datetime.now(UTC)
        await PostgresAuditSink(sessions).write(
            AuditEvent(
                audit_id="audit_pg",
                request_id="req",
                trace_id="trace",
                tenant_id="tenant-a",
                biz_domain="legal",
                caller_type="service",
                caller_id="svc",
                operation="file.get_resource",
                resource_id="res_pg",
                session_id=None,
                job_id=None,
                decision="ALLOW",
                result="SUCCESS",
                error_code=None,
                duration_ms=1,
                created_at=now,
            )
        )
        reconciliation = PostgresReconciliationStore(sessions)
        await reconciliation.record(
            "recon_pg",
            "UPLOAD_COMPENSATION",
            {"tenant_id": "tenant-a", "biz_domain": "legal", "resource_id": "res_pg"},
        )
        await sessions().commit()
        assert (
            await sessions().scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.audit_id == "audit_pg")
            )
            == 1
        )
        assert (
            await sessions().scalar(
                select(func.count())
                .select_from(ReconciliationRecordRow)
                .where(ReconciliationRecordRow.key == "recon_pg")
            )
            == 1
        )
        await reconciliation.resolve("recon_pg", "tenant_a", "files")
        await sessions().commit()
    finally:
        await sessions.remove()
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_primary_session_uses_isolated_reconciliation_transaction() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    key = "stream-provider-orphan:failed-primary"
    isolated = PostgresIndependentReconciliationStore(engine)
    try:
        await sessions().execute(
            ReconciliationRecordRow.__table__.delete().where(ReconciliationRecordRow.key == key)
        )
        await sessions().commit()
        await files_with_duplicate_failure(sessions)
        assert not sessions().is_active
        await isolated.record(
            key,
            "STREAM_PROVIDER_ORPHAN",
            {
                "tenant_id": "tenant-a",
                "biz_domain": "legal",
                "session_id": "failed-primary",
                "provider_type": "fake",
                "provider_session_id": "provider-failed-primary",
                "fencing_token": 11,
                "required_action": "STOP_PROVIDER_STREAM",
            },
        )
        await sessions().rollback()
        await sessions.remove()
        assert (
            await sessions().scalar(
                select(func.count())
                .select_from(ReconciliationRecordRow)
                .where(ReconciliationRecordRow.key == key)
            )
            == 1
        )
    finally:
        await sessions().rollback()
        await sessions.remove()
        await engine.dispose()


async def files_with_duplicate_failure(sessions: object) -> None:
    repository = PostgresFileRepository(sessions)  # type: ignore[arg-type]
    await repository.add(resource("res_pg_isolation"))
    await sessions().commit()  # type: ignore[attr-defined]
    with pytest.raises(IntegrityError):
        await repository.add(resource("res_pg_isolation"))


@pytest.mark.asyncio
async def test_durable_idempotency_survives_new_store_instance() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    scope = ("tenant-a", "legal", "svc", "file.initialize_upload", "idem-pg")
    try:
        store = PostgresIdempotencyStore(sessions)
        await store.fail(scope)
        await sessions().commit()
        assert await store.reserve(scope, "hash") == ("OWNER", None)
        await store.complete(scope, "hash", {"resource_id": "res"})
        await sessions().commit()
        await sessions.remove()
        replacement = PostgresIdempotencyStore(sessions)
        assert await replacement.reserve(scope, "hash") == (
            "COMPLETED",
            {"resource_id": "res"},
        )
        await sessions().rollback()
    finally:
        await sessions.remove()
        await engine.dispose()


@pytest.mark.asyncio
async def test_stream_and_job_repository_state_updates_are_scoped() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    now = datetime.now(UTC)
    streams = PostgresStreamSessionRepository(sessions)
    jobs = PostgresProcessingJobRepository(sessions)
    stream = StreamSession(
        "session-pg",
        "tenant-a",
        "legal",
        "svc",
        "WEBRTC",
        "INGRESS",
        StreamSessionStatus.CREATING,
        now + timedelta(minutes=5),
        "opaque-endpoint",
        now,
        now,
    )
    stream.provider_type = "fake"
    stream.media_server_session_id = "provider-session"
    stream.stream_key = "opaque-key"
    stream.input_protocol = "WEBRTC"
    stream.output_protocol = "WEBRTC"
    stream.endpoint = "opaque-endpoint"
    stream.connection_state = StreamConnectionState.CONNECTING
    stream.fencing_token = 9
    job = ProcessingJob(
        "job-pg",
        "tenant-a",
        "legal",
        "THUMBNAIL",
        "res-pg",
        (),
        ProcessingJobStatus.PENDING,
        "processor",
        0,
        now,
        now,
    )
    try:
        await sessions().execute(
            StreamSessionRow.__table__.delete().where(StreamSessionRow.session_id == "session-pg")
        )
        await sessions().execute(
            ProcessingJobRow.__table__.delete().where(ProcessingJobRow.job_id == "job-pg")
        )
        await sessions().execute(
            StreamEventRow.__table__.delete().where(StreamEventRow.event_id == "event-pg")
        )
        await streams.add(stream)
        await jobs.add(job)
        stream.transition_to(StreamSessionStatus.READY)
        job.transition_to(ProcessingJobStatus.QUEUED)
        await streams.save(stream)
        await jobs.save(job)
        await PostgresStreamEventSink(sessions).write_stream_event(
            StreamEvent(
                "event-pg",
                "tenant-a",
                "legal",
                "session-pg",
                StreamEventType.STREAM_CREATED,
                "fake",
                now,
                {"connection_state": "CONNECTING"},
            )
        )
        await sessions().commit()
        loaded_stream = await streams.get_by_scope_and_id("tenant-a", "legal", "session-pg")
        loaded_job = await jobs.get_by_scope_and_id("tenant-a", "legal", "job-pg")
        assert loaded_stream is not None
        assert loaded_stream.status is StreamSessionStatus.READY
        assert loaded_stream.provider_type == "fake"
        assert loaded_stream.fencing_token == 9
        assert loaded_job is not None
        assert loaded_job.status is ProcessingJobStatus.QUEUED
        assert await streams.get_by_scope_and_id("tenant-b", "legal", "session-pg") is None
        assert await jobs.get_by_scope_and_id("tenant-a", "finance", "job-pg") is None
        assert len(await streams.list_recoverable("tenant-a", "legal")) >= 1
        assert (
            await sessions().scalar(
                select(func.count())
                .select_from(StreamEventRow)
                .where(
                    StreamEventRow.tenant_id == "tenant-a",
                    StreamEventRow.biz_domain == "legal",
                    StreamEventRow.session_id == "session-pg",
                )
            )
            == 1
        )
    finally:
        await sessions.rollback()
        await sessions.remove()
        await engine.dispose()
