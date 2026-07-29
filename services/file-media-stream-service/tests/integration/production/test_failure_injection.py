from typing import Any

import pytest
from fastapi.testclient import TestClient
from minio import Minio
from minio.error import S3Error
from sqlalchemy import select

from file_media_stream_service.adapters.clock import SystemClock, UuidIdentifierFactory
from file_media_stream_service.adapters.event_bus import InMemoryEventBus
from file_media_stream_service.adapters.media_server import InMemoryMediaServer
from file_media_stream_service.adapters.object_storage.minio import (
    MinioObjectStorage,
    create_minio_client,
)
from file_media_stream_service.adapters.persistence import (
    InMemoryProcessingJobRepository,
    InMemoryReconciliationStore,
    InMemoryState,
    InMemoryStreamSessionRepository,
)
from file_media_stream_service.adapters.persistence.postgres import (
    PostgresFileRepository,
    create_engine,
    create_session_registry,
)
from file_media_stream_service.adapters.persistence.postgres.models import FileResourceRow
from file_media_stream_service.adapters.processors import InMemoryProcessor
from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.application.use_cases import UseCases
from file_media_stream_service.bootstrap import ProductionContainer, build_container
from file_media_stream_service.config import Settings
from file_media_stream_service.main import create_app

pytestmark = pytest.mark.production_integration
DATABASE_URL = "postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream"


class CommitFailure:
    async def commit(self) -> None:
        raise RuntimeError("database credential must not escape")

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class Ready:
    async def check(self) -> dict[str, str]:
        return {"postgres": "ok", "redis": "ok", "minio": "ok"}


class FailingFiles:
    async def add(self, resource: Any) -> None:
        raise RuntimeError("postgres update failed")

    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None:
        return None

    async def get_by_scope_and_id(self, tenant_id: str, biz_domain: str, resource_id: str) -> None:
        return None


def request_context() -> RequestContext:
    return RequestContext(
        request_id="failure",
        trace_id="failure-trace",
        tenant_id="tenant-failure",
        biz_domain="legal",
        caller_type="service",
        caller_id="service-failure",
        idempotency_key="failure-key",
    )


def test_postgres_commit_failure_is_generic_and_rolls_back() -> None:
    local = build_container(Settings(environment="test"))
    assert not isinstance(local, ProductionContainer)
    container = ProductionContainer(
        entry=local.entry,
        gateway=local.gateway,
        transaction=CommitFailure(),  # type: ignore[arg-type]
        readiness=Ready(),  # type: ignore[arg-type]
    )
    response = TestClient(create_app(container, Settings(environment="test"))).get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "error": "transaction_failed",
    }
    assert "credential" not in response.text


@pytest.mark.asyncio
async def test_minio_success_then_postgres_failure_is_compensated() -> None:
    state = InMemoryState()
    storage = MinioObjectStorage(
        create_minio_client("localhost:59000", "fms_local", "fms_local_only_secret", secure=False),
        "file-media-stream",
    )
    use_cases = UseCases(
        files=FailingFiles(),  # type: ignore[arg-type]
        sessions=InMemoryStreamSessionRepository(state),
        jobs=InMemoryProcessingJobRepository(state),
        storage=storage,
        media_server=InMemoryMediaServer(),
        processor=InMemoryProcessor(),
        events=InMemoryEventBus(),
        clock=SystemClock(),
        ids=UuidIdentifierFactory(),
        reconciliation=InMemoryReconciliationStore(),
    )
    with pytest.raises(RuntimeError, match="postgres update failed"):
        await use_cases.initialize_upload(
            request_context(),
            {
                "filename": "failure.txt",
                "owner_type": "case",
                "owner_id": "case",
                "mime_type": "text/plain",
                "size_bytes": 1,
            },
        )


@pytest.mark.asyncio
async def test_minio_failure_does_not_persist_postgres_resource() -> None:
    engine = create_engine(DATABASE_URL, 2, 1, 3)
    sessions = create_session_registry(engine)
    state = InMemoryState()
    denied = MinioObjectStorage(
        Minio("localhost:59000", access_key="bad", secret_key="bad-secret", secure=False),
        "file-media-stream",
    )
    original_initialize = denied.initialize_upload

    async def checked_initialize(object_key: str, mime_type: str, size_bytes: int) -> str:
        await denied.get_metadata(object_key)
        return await original_initialize(object_key, mime_type, size_bytes)

    denied.initialize_upload = checked_initialize
    use_cases = UseCases(
        files=PostgresFileRepository(sessions),
        sessions=InMemoryStreamSessionRepository(state),
        jobs=InMemoryProcessingJobRepository(state),
        storage=denied,
        media_server=InMemoryMediaServer(),
        processor=InMemoryProcessor(),
        events=InMemoryEventBus(),
        clock=SystemClock(),
        ids=UuidIdentifierFactory(),
        reconciliation=InMemoryReconciliationStore(),
    )
    try:
        with pytest.raises(S3Error):
            await use_cases.initialize_upload(
                request_context(),
                {
                    "filename": "failure.txt",
                    "owner_type": "case",
                    "owner_id": "case",
                    "mime_type": "text/plain",
                    "size_bytes": 1,
                },
            )
        assert (
            await sessions().scalar(
                select(FileResourceRow).where(
                    FileResourceRow.tenant_id == "tenant-failure",
                    FileResourceRow.biz_domain == "legal",
                    FileResourceRow.created_by == "service-failure",
                )
            )
            is None
        )
    finally:
        await sessions().rollback()
        await sessions.remove()
        await engine.dispose()
