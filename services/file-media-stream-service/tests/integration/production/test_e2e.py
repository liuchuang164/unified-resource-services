from sqlalchemy import delete, select

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.coordination.redis import (
    RedisCoordinatedIdempotencyStore,
    RedisCoordination,
    RedisQuotaChecker,
    RedisReplayProtector,
    create_redis_client,
)
from file_media_stream_service.adapters.object_storage.minio import (
    MinioObjectStorage,
    create_minio_client,
)
from file_media_stream_service.adapters.persistence.postgres import (
    PostgresAuditSink,
    PostgresFileRepository,
    PostgresIdempotencyStore,
    PostgresProcessingJobRepository,
    PostgresReconciliationStore,
    PostgresStreamSessionRepository,
    create_engine,
    create_session_registry,
)
from file_media_stream_service.adapters.persistence.postgres.models import (
    AuditEventRow,
    FileResourceRow,
    IdempotencyRecordRow,
)
from file_media_stream_service.adapters.production_boundaries import (
    StructuredEventBus,
    UnavailableMediaServer,
    UnavailableProcessor,
)
from file_media_stream_service.application.dto import (
    RequestContext,
    ToolExecuteRequest,
    UnifiedRequest,
)
from file_media_stream_service.application.use_cases import UseCases
from file_media_stream_service.entry import UnifiedEntry
from file_media_stream_service.gateway import ToolGateway
from file_media_stream_service.security import AuthorizationRule, FakeSecurity

DATABASE_URL = "postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream"


async def test_business_and_agent_pipeline_use_real_production_infrastructure() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    redis = create_redis_client("redis://localhost:56379/14", 1)
    await redis.flushdb()
    coordination = RedisCoordination(redis)
    storage = MinioObjectStorage(
        create_minio_client("localhost:59000", "fms_local", "fms_local_only_secret", secure=False),
        "file-media-stream",
    )
    security = FakeSecurity(
        rules=(
            AuthorizationRule(
                "service-e2e", "tenant-e2e", "legal", "file.initialize_upload", allowed=True
            ),
            AuthorizationRule(
                "agent-e2e", "tenant-e2e", "legal", "file.get_resource", allowed=True
            ),
        ),
        valid_tokens=frozenset({"test-only-capability"}),
    )
    files = PostgresFileRepository(sessions)
    clock = SystemClock()
    use_cases = UseCases(
        files=files,
        sessions=PostgresStreamSessionRepository(sessions),
        jobs=PostgresProcessingJobRepository(sessions),
        storage=storage,
        media_server=UnavailableMediaServer(),
        processor=UnavailableProcessor(),
        events=StructuredEventBus(),
        clock=clock,
        ids=UuidIdentifierFactory(),
        reconciliation=PostgresReconciliationStore(sessions),
    )
    idempotency = RedisCoordinatedIdempotencyStore(coordination, PostgresIdempotencyStore(sessions))
    entry = UnifiedEntry(
        use_cases,
        security,
        security,
        security,
        RedisQuotaChecker(redis),
        RedisReplayProtector(redis),
        idempotency,
        PostgresAuditSink(sessions),
        clock,
    )
    try:
        await sessions().execute(
            delete(AuditEventRow).where(AuditEventRow.tenant_id == "tenant-e2e")
        )
        await sessions().execute(
            delete(IdempotencyRecordRow).where(IdempotencyRecordRow.tenant_id == "tenant-e2e")
        )
        await sessions().execute(
            delete(FileResourceRow).where(FileResourceRow.tenant_id == "tenant-e2e")
        )
        await sessions().commit()
        service_context = RequestContext(
            request_id="e2e-business",
            trace_id="trace-business",
            tenant_id="tenant-e2e",
            biz_domain="legal",
            caller_type="service",
            caller_id="service-e2e",
            idempotency_key="business-upload",
            nonce="business-nonce",
        )
        created = await entry.execute(
            UnifiedRequest(
                api_version="v1",
                operation="file.initialize_upload",
                context=service_context,
                payload={
                    "filename": "e2e.txt",
                    "owner_type": "case",
                    "owner_id": "case-e2e",
                    "mime_type": "text/plain",
                    "size_bytes": 3,
                },
            )
        )
        assert created.success
        await sessions().commit()
        resource_id = str(created.data["resource"]["resource_id"])  # type: ignore[index]
        row = await sessions().scalar(
            select(FileResourceRow).where(
                FileResourceRow.tenant_id == "tenant-e2e",
                FileResourceRow.biz_domain == "legal",
                FileResourceRow.resource_id == resource_id,
            )
        )
        assert row is not None

        agent_context = RequestContext(
            request_id="e2e-agent",
            trace_id="trace-agent",
            tenant_id="tenant-e2e",
            biz_domain="legal",
            caller_type="agent",
            caller_id="agent-e2e",
            agent_id="agent-e2e",
            tool_call_id="tool-e2e",
            capability_token="test-only-capability",
            nonce="agent-nonce",
        )
        tool_response = await ToolGateway(entry).execute(
            ToolExecuteRequest(
                tool_name="file.get_resource",
                context=agent_context,
                params={"resource_id": resource_id},
            )
        )
        assert tool_response.response.success
        assert tool_response.response.data["resource"]["resource_id"] == resource_id  # type: ignore[index]
        await sessions().commit()
    finally:
        await sessions.remove()
        await redis.aclose()
        await engine.dispose()
