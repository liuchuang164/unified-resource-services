from dataclasses import dataclass

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.coordination.redis import (
    RedisCoordinatedIdempotencyStore,
    RedisCoordination,
    RedisQuotaChecker,
    RedisReplayProtector,
    create_redis_client,
)
from file_media_stream_service.adapters.event_bus import InMemoryEventBus
from file_media_stream_service.adapters.media_server import InMemoryMediaServer
from file_media_stream_service.adapters.object_storage import InMemoryObjectStorage
from file_media_stream_service.adapters.object_storage.minio import (
    MinioObjectStorage,
    create_minio_client,
)
from file_media_stream_service.adapters.persistence import (
    InMemoryFileRepository,
    InMemoryIdempotencyStore,
    InMemoryProcessingJobRepository,
    InMemoryReconciliationStore,
    InMemoryState,
    InMemoryStreamSessionRepository,
)
from file_media_stream_service.adapters.persistence.postgres import (
    PostgresAuditSink,
    PostgresFileRepository,
    PostgresHealth,
    PostgresIdempotencyStore,
    PostgresProcessingJobRepository,
    PostgresReconciliationStore,
    PostgresStreamSessionRepository,
    PostgresTransactionManager,
    create_engine,
    create_session_registry,
)
from file_media_stream_service.adapters.processors import InMemoryProcessor
from file_media_stream_service.adapters.production_boundaries import (
    ExternalSecurityBoundary,
    StructuredEventBus,
    UnavailableMediaServer,
    UnavailableProcessor,
)
from file_media_stream_service.adapters.readiness import ProductionReadiness
from file_media_stream_service.application.use_cases import UseCases
from file_media_stream_service.audit import InMemoryAuditSink
from file_media_stream_service.config import Settings
from file_media_stream_service.entry import UnifiedEntry
from file_media_stream_service.gateway import ToolGateway
from file_media_stream_service.security import AuthorizationRule, FakeSecurity

OPERATIONS = (
    "file.initialize_upload",
    "file.get_resource",
    "media.create_stream_session",
    "media.get_stream_session",
    "media.close_stream_session",
    "media.submit_processing_job",
    "media.get_processing_job",
)


@dataclass(slots=True)
class Container:
    entry: UnifiedEntry
    gateway: ToolGateway
    state: InMemoryState
    storage: InMemoryObjectStorage
    media_server: InMemoryMediaServer
    processor: InMemoryProcessor
    events: InMemoryEventBus
    audit: InMemoryAuditSink
    security: FakeSecurity
    idempotency: InMemoryIdempotencyStore
    reconciliation: InMemoryReconciliationStore


@dataclass(slots=True)
class ProductionContainer:
    entry: UnifiedEntry
    gateway: ToolGateway
    transaction: PostgresTransactionManager
    readiness: ProductionReadiness


def build_container(settings: Settings | None = None) -> Container | ProductionContainer:
    settings = settings or Settings()
    if settings.infrastructure_mode == "production":
        return build_production_container(settings)
    if settings.environment not in {"development", "test"}:
        raise RuntimeError("Fake adapters may only be used in development or test environments")
    state = InMemoryState()
    storage = InMemoryObjectStorage()
    media_server = InMemoryMediaServer()
    processor = InMemoryProcessor()
    events = InMemoryEventBus()
    clock = SystemClock()
    audit = InMemoryAuditSink()
    idempotency = InMemoryIdempotencyStore()
    reconciliation = InMemoryReconciliationStore()
    rules = tuple(
        AuthorizationRule("dev-service", "dev-tenant", "development", operation, allowed=True)
        for operation in OPERATIONS
    ) + tuple(
        AuthorizationRule("dev-agent", "dev-tenant", "development", operation, allowed=True)
        for operation in OPERATIONS
    )
    security = FakeSecurity(rules=rules, valid_tokens=frozenset({"dev-capability-token"}))
    use_cases = UseCases(
        files=InMemoryFileRepository(state),
        sessions=InMemoryStreamSessionRepository(state),
        jobs=InMemoryProcessingJobRepository(state),
        storage=storage,
        media_server=media_server,
        processor=processor,
        events=events,
        clock=clock,
        ids=UuidIdentifierFactory(),
        reconciliation=reconciliation,
        stream_lease_seconds=settings.stream_lease_seconds,
    )
    entry = UnifiedEntry(
        use_cases=use_cases,
        identity=security,
        capability=security,
        authorization=security,
        quota=security,
        replay=security,
        idempotency=idempotency,
        audit=audit,
        clock=clock,
        api_version=settings.api_version,
    )
    return Container(
        entry=entry,
        gateway=ToolGateway(entry),
        state=state,
        storage=storage,
        media_server=media_server,
        processor=processor,
        events=events,
        audit=audit,
        security=security,
        idempotency=idempotency,
        reconciliation=reconciliation,
    )


def build_production_container(settings: Settings) -> ProductionContainer:
    if settings.infrastructure_mode != "production":
        raise RuntimeError("Production container requires production infrastructure mode")
    database_url = _required_secret(settings.database_url, "DATABASE_URL")
    redis_url = _required_secret(settings.redis_url, "REDIS_URL")
    minio_access_key = _required_secret(settings.minio_access_key, "MINIO_ACCESS_KEY")
    minio_secret_key = _required_secret(settings.minio_secret_key, "MINIO_SECRET_KEY")
    if settings.minio_endpoint is None or settings.minio_bucket is None:
        raise RuntimeError("MinIO configuration is incomplete")

    engine = create_engine(
        database_url,
        settings.database_pool_size,
        settings.database_max_overflow,
        settings.database_connect_timeout_seconds,
    )
    sessions = create_session_registry(engine)
    transaction = PostgresTransactionManager(sessions)
    redis_client = create_redis_client(redis_url, settings.redis_socket_timeout_seconds)
    coordination = RedisCoordination(redis_client, settings.redis_lease_ttl_seconds)
    minio = MinioObjectStorage(
        create_minio_client(
            settings.minio_endpoint,
            minio_access_key,
            minio_secret_key,
            secure=settings.minio_secure,
        ),
        settings.minio_bucket,
        upload_ttl_seconds=settings.minio_presigned_upload_ttl_seconds,
        download_ttl_seconds=settings.minio_presigned_download_ttl_seconds,
    )
    clock = SystemClock()
    reconciliation = PostgresReconciliationStore(sessions)
    durable_idempotency = PostgresIdempotencyStore(sessions)
    idempotency = RedisCoordinatedIdempotencyStore(coordination, durable_idempotency)
    security = ExternalSecurityBoundary()
    use_cases = UseCases(
        files=PostgresFileRepository(sessions),
        sessions=PostgresStreamSessionRepository(sessions),
        jobs=PostgresProcessingJobRepository(sessions),
        storage=minio,
        media_server=UnavailableMediaServer(),
        processor=UnavailableProcessor(),
        events=StructuredEventBus(),
        clock=clock,
        ids=UuidIdentifierFactory(),
        reconciliation=reconciliation,
        stream_lease_seconds=settings.stream_lease_seconds,
    )
    entry = UnifiedEntry(
        use_cases=use_cases,
        identity=security,
        capability=security,
        authorization=security,
        quota=RedisQuotaChecker(redis_client),
        replay=RedisReplayProtector(redis_client),
        idempotency=idempotency,
        audit=PostgresAuditSink(sessions),
        clock=clock,
        api_version=settings.api_version,
    )
    readiness = ProductionReadiness(
        postgres=PostgresHealth(engine),
        redis=coordination,
        minio=minio,
    )
    return ProductionContainer(
        entry=entry,
        gateway=ToolGateway(entry),
        transaction=transaction,
        readiness=readiness,
    )


def _required_secret(value: object, name: str) -> str:
    if value is None or not hasattr(value, "get_secret_value"):
        raise RuntimeError(f"{name} is required")
    return str(value.get_secret_value())
