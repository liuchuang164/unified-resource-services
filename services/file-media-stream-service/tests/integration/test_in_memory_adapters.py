from datetime import UTC, datetime

import pytest

from file_media_stream_service.adapters.object_storage import InMemoryObjectStorage
from file_media_stream_service.adapters.persistence import (
    InMemoryFileRepository,
    InMemoryState,
)
from file_media_stream_service.domain.entities import FileResource
from file_media_stream_service.domain.enums import FileResourceStatus


@pytest.mark.asyncio
async def test_repository_scope_is_part_of_lookup_key() -> None:
    state = InMemoryState()
    repository = InMemoryFileRepository(state)
    now = datetime.now(UTC)
    resource = FileResource(
        "same-id",
        "tenant-a",
        "legal",
        "case",
        "case-1",
        "a.pdf",
        "a.pdf",
        "key",
        "application/pdf",
        1,
        None,
        FileResourceStatus.PENDING_UPLOAD,
        1,
        "caller",
        now,
        now,
    )
    await repository.add(resource)
    found = await repository.get_by_scope_and_id("tenant-a", "legal", "same-id")
    assert found == resource
    assert found is not resource
    assert await repository.get_by_scope_and_id("tenant-b", "legal", "same-id") is None
    assert await repository.get_by_scope_and_id("tenant-a", "robot", "same-id") is None


@pytest.mark.asyncio
async def test_upload_abort_compensates_initialized_reference() -> None:
    storage = InMemoryObjectStorage()
    await storage.initialize_upload("key", "application/pdf", 1)
    await storage.abort_upload("key")
    assert storage.uploads == {}
