from dataclasses import dataclass

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.coordination.redis import (
    RedisCoordinatedIdempotencyStore,
    RedisCoordination,
    RedisQuotaChecker,
    RedisRangeAccessGrantStore,
    RedisReplayProtector,
    RedisUploadPartGrantStore,
    create_redis_client,
)
from file_media_stream_service.adapters.event_bus import InMemoryEventBus
from file_media_stream_service.adapters.file_commit_reconciliation import (
    FileMetadataCommitReconciler,
)
from file_media_stream_service.adapters.file_verification import MetadataSafetyValidator
from file_media_stream_service.adapters.media_provider import (
    FakeMediaProvider,
    GenericHttpMediaProvider,
    InMemoryStreamCoordination,
)
from file_media_stream_service.adapters.media_server import InMemoryMediaServer
from file_media_stream_service.adapters.object_storage import InMemoryObjectStorage
from file_media_stream_service.adapters.object_storage.minio import (
    MinioObjectStorage,
    create_minio_client,
)
from file_media_stream_service.adapters.persistence import (
    InMemoryFileRepository,
    InMemoryFileUploadSessionRepository,
    InMemoryFileVersionRepository,
    InMemoryIdempotencyStore,
    InMemoryProcessingJobRepository,
    InMemoryReconciliationStore,
    InMemoryState,
    InMemoryStreamEventSink,
    InMemoryStreamSessionRepository,
)
from file_media_stream_service.adapters.persistence.postgres import (
    PostgresAuditSink,
    PostgresFileRepository,
    PostgresFileUploadSessionRepository,
    PostgresFileVersionRepository,
    PostgresHealth,
    PostgresIdempotencyStore,
    PostgresIndependentReconciliationStore,
    PostgresProcessingJobRepository,
    PostgresStreamEventSink,
    PostgresStreamSessionRepository,
    PostgresTransactionManager,
    create_engine,
    create_session_registry,
)
from file_media_stream_service.adapters.processors import InMemoryProcessor
from file_media_stream_service.adapters.production_boundaries import (
    ExternalSecurityBoundary,
    StructuredEventBus,
    UnavailableMediaProvider,
    UnavailableMediaServer,
    UnavailableProcessor,
)
from file_media_stream_service.adapters.provisioning_compensation import (
    StreamProvisioningCompensator,
)
from file_media_stream_service.adapters.range_access import (
    InMemoryRangeAccessGrantStore,
    InMemoryUploadPartGrantStore,
)
from file_media_stream_service.adapters.readiness import ProductionReadiness
from file_media_stream_service.application.ports.media_provider import MediaProviderPort
from file_media_stream_service.application.use_cases import StreamLifecycleService, UseCases
from file_media_stream_service.audit import InMemoryAuditSink
from file_media_stream_service.config import Settings
from file_media_stream_service.entry import UnifiedEntry
from file_media_stream_service.gateway import ToolGateway
from file_media_stream_service.security import AuthorizationRule, FakeSecurity
from file_media_stream_service.workers import StreamLifecycleWorker

OPERATIONS = (
    "file.initialize_upload",
    "file.get_resource",
    "file.complete_upload",
    "file.abort_upload",
    "file.create_download_url",
    "file.read_range",
    "file.get_metadata",
    "file.delete_file",
    "file.create_upload_part_urls",
    "file.create_version_upload",
    "file.switch_current_version",
    "file.delete_version",
    "media.create_stream_session",
    "media.get_stream_session",
    "media.close_stream_session",
    "media.submit_processing_job",
    "media.get_processing_job",
)
AUTHORIZATION_ACTIONS = (
    "file:create_upload",
    "file:upload_part",
    "file:complete_upload",
    "file:read",
    "file:create_version",
    "file:delete_version",
    "file:delete",
    "media_stream:create",
    "media_stream:publish",
    "media_stream:subscribe",
    "media_stream:close",
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
    media_provider: FakeMediaProvider
    stream_coordination: InMemoryStreamCoordination
    stream_events: InMemoryStreamEventSink
    provisioning_compensator: StreamProvisioningCompensator


@dataclass(slots=True)
class ProductionContainer:
    entry: UnifiedEntry
    gateway: ToolGateway
    transaction: PostgresTransactionManager
    readiness: ProductionReadiness
    lifecycle: StreamLifecycleService | None = None
    lifecycle_worker: StreamLifecycleWorker | None = None
    provisioning_compensator: StreamProvisioningCompensator | None = None
    file_metadata_commit_tracker: FileMetadataCommitReconciler | None = None


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
    media_provider = FakeMediaProvider(media_server)
    stream_coordination = InMemoryStreamCoordination()
    stream_events = InMemoryStreamEventSink()
    provisioning_compensator = StreamProvisioningCompensator(
        media_provider, stream_coordination, reconciliation
    )
    rules = tuple(
        AuthorizationRule("dev-service", "dev-tenant", "development", operation, allowed=True)
        for operation in AUTHORIZATION_ACTIONS
    ) + tuple(
        AuthorizationRule("dev-agent", "dev-tenant", "development", operation, allowed=True)
        for operation in AUTHORIZATION_ACTIONS
    )
    security = FakeSecurity(rules=rules, valid_tokens=frozenset({"dev-capability-token"}))
    use_cases = UseCases(
        files=InMemoryFileRepository(state),
        file_versions=InMemoryFileVersionRepository(state),
        file_uploads=InMemoryFileUploadSessionRepository(state),
        range_grants=InMemoryRangeAccessGrantStore(),
        upload_part_grants=InMemoryUploadPartGrantStore(),
        malware_scanner=MetadataSafetyValidator(),
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
        media_provider=media_provider,
        stream_coordination=stream_coordination,
        stream_events=stream_events,
        provisioning_compensator=provisioning_compensator,
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
        media_provider=media_provider,
        stream_coordination=stream_coordination,
        stream_events=stream_events,
        provisioning_compensator=provisioning_compensator,
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
    reconciliation = PostgresIndependentReconciliationStore(engine)
    durable_idempotency = PostgresIdempotencyStore(sessions)
    security = ExternalSecurityBoundary()
    media_provider: MediaProviderPort
    if settings.media_provider_base_url and settings.media_provider_api_token:
        media_provider = GenericHttpMediaProvider(
            settings.media_provider_base_url,
            api_token=settings.media_provider_api_token.get_secret_value(),
            timeout_seconds=settings.media_provider_timeout_seconds,
        )
    else:
        media_provider = UnavailableMediaProvider()
    stream_events = PostgresStreamEventSink(sessions)
    provisioning_compensator = StreamProvisioningCompensator(
        media_provider, coordination, reconciliation
    )
    file_metadata_commit_tracker = FileMetadataCommitReconciler(reconciliation)
    idempotency = RedisCoordinatedIdempotencyStore(
        coordination,
        durable_idempotency,
        on_durable_complete=provisioning_compensator.clear,
    )
    use_cases = UseCases(
        files=PostgresFileRepository(sessions),
        file_versions=PostgresFileVersionRepository(sessions),
        file_uploads=PostgresFileUploadSessionRepository(sessions),
        range_grants=RedisRangeAccessGrantStore(redis_client),
        upload_part_grants=RedisUploadPartGrantStore(redis_client),
        malware_scanner=MetadataSafetyValidator(),
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
        media_provider=media_provider,
        stream_coordination=coordination,
        stream_events=stream_events,
        transactions=transaction,
        provisioning_compensator=provisioning_compensator,
        file_metadata_commit_tracker=file_metadata_commit_tracker,
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
    lifecycle = StreamLifecycleService(
        sessions=PostgresStreamSessionRepository(sessions),
        provider=media_provider,
        coordination=coordination,
        events=stream_events,
        reconciliation=reconciliation,
        clock=clock,
        ids=UuidIdentifierFactory(),
    )
    lifecycle_worker = StreamLifecycleWorker(lifecycle, transactions=transaction)
    return ProductionContainer(
        entry=entry,
        gateway=ToolGateway(entry),
        transaction=transaction,
        readiness=readiness,
        lifecycle=lifecycle,
        lifecycle_worker=lifecycle_worker,
        provisioning_compensator=provisioning_compensator,
        file_metadata_commit_tracker=file_metadata_commit_tracker,
    )


def _required_secret(value: object, name: str) -> str:
    if value is None or not hasattr(value, "get_secret_value"):
        raise RuntimeError(f"{name} is required")
    return str(value.get_secret_value())
