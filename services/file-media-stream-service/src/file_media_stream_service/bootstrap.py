from dataclasses import dataclass

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.event_bus import InMemoryEventBus
from file_media_stream_service.adapters.media_server import InMemoryMediaServer
from file_media_stream_service.adapters.object_storage import InMemoryObjectStorage
from file_media_stream_service.adapters.persistence import (
    InMemoryFileRepository,
    InMemoryIdempotencyStore,
    InMemoryProcessingJobRepository,
    InMemoryReconciliationStore,
    InMemoryState,
    InMemoryStreamSessionRepository,
)
from file_media_stream_service.adapters.processors import InMemoryProcessor
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


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
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
