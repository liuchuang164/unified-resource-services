import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.bootstrap import Container
from file_media_stream_service.domain.enums import FileResourceStatus, UploadSessionStatus
from file_media_stream_service.domain.exceptions import (
    FileResourceNotFound,
    InvalidStateTransition,
)


async def _stream(content: bytes):
    midpoint = max(1, len(content) // 2)
    yield content[:midpoint]
    if midpoint < len(content):
        yield content[midpoint:]


def _context(**changes: object) -> RequestContext:
    values: dict[str, object] = {
        "request_id": "phase31-request",
        "trace_id": "phase31-trace",
        "tenant_id": "dev-tenant",
        "biz_domain": "development",
        "caller_type": "service",
        "caller_id": "dev-service",
    }
    values.update(changes)
    return RequestContext.model_validate(values)


async def _initialize(
    container: Container, context: RequestContext, size: int
) -> dict[str, object]:
    return await container.entry.use_cases.initialize_upload(
        context,
        {
            "filename": "phase31.bin",
            "mime_type": "application/octet-stream",
            "size_bytes": size,
            "owner_type": "case",
            "owner_id": "phase31-case",
        },
    )


async def _put_part(
    container: Container,
    context: RequestContext,
    resource_id: str,
    upload_session_id: str,
    content: bytes,
) -> str:
    references = await container.entry.use_cases.create_upload_part_references(
        context,
        {
            "resource_id": resource_id,
            "upload_session_id": upload_session_id,
            "parts": [1],
        },
    )
    reference = references["parts"][0]["upload_reference"]
    _, etag = await container.entry.consume_upload_part_reference(
        reference, _stream(content), len(content)
    )
    return etag


async def _create_available(
    container: Container, context: RequestContext, content: bytes
) -> tuple[str, str]:
    initialized = await _initialize(container, context, len(content))
    resource_id = str(initialized["resource"]["resource_id"])
    upload_id = str(initialized["upload_session_id"])
    etag = await _put_part(container, context, resource_id, upload_id, content)
    completed = await container.entry.use_cases.complete_upload(
        context,
        {
            "resource_id": resource_id,
            "upload_id": upload_id,
            "parts": [{"part_number": 1, "etag": etag}],
            "checksum": hashlib.sha256(content).hexdigest(),
        },
    )
    return resource_id, str(completed["version"]["version_id"])


@pytest.mark.asyncio
async def test_binary_upload_endpoint_is_one_time_and_audited_without_payload(
    container: Container, client: TestClient
) -> None:
    context = _context()
    content = b"binary-only-data"
    initialized = await _initialize(container, context, len(content))
    resource_id = str(initialized["resource"]["resource_id"])
    upload_id = str(initialized["upload_session_id"])
    references = await container.entry.use_cases.create_upload_part_references(
        context,
        {"resource_id": resource_id, "upload_session_id": upload_id, "parts": [1]},
    )
    reference = str(references["parts"][0]["upload_reference"])

    response = client.put(
        "/api/v1/files/upload-part",
        headers={"X-Upload-Part-Reference": reference, "Content-Type": "application/octet-stream"},
        content=content,
    )

    assert response.status_code == 204
    assert response.headers["x-part-number"] == "1"
    assert response.headers["etag"]
    assert (
        client.put(
            "/api/v1/files/upload-part",
            headers={"X-Upload-Part-Reference": reference},
            content=content,
        ).status_code
        == 403
    )
    event = next(
        item
        for item in reversed(container.audit.events)
        if item.operation == "file.upload_part.stream" and item.result == "SUCCESS"
    )
    serialized = str(asdict(event))
    assert event.operation == "file.upload_part.stream"
    assert event.resource_id == resource_id
    assert event.length == len(content)
    assert content.decode() not in serialized
    assert reference not in serialized
    assert "object_key" not in serialized
    denied = container.audit.events[-1]
    assert denied.decision == "DENY"
    assert denied.error_code == "UPLOAD_PART_REFERENCE_DENIED"
    assert reference not in str(asdict(denied))


@pytest.mark.asyncio
async def test_binary_upload_stream_limits_and_infrastructure_failure_mapping(
    container: Container, client: TestClient
) -> None:
    context = _context()
    initialized = await _initialize(container, context, 3)
    resource_id = str(initialized["resource"]["resource_id"])
    upload_id = str(initialized["upload_session_id"])
    references = await container.entry.use_cases.create_upload_part_references(
        context,
        {"resource_id": resource_id, "upload_session_id": upload_id, "parts": [1]},
    )
    reference = str(references["parts"][0]["upload_reference"])
    oversized = client.put(
        "/api/v1/files/upload-part",
        headers={
            "X-Upload-Part-Reference": reference,
            "Content-Length": str(64 * 1024 * 1024 + 1),
        },
        content=b"x",
    )
    assert oversized.status_code == 413

    async def unavailable_stream(*args: object, **kwargs: object) -> str:
        del args, kwargs
        raise RuntimeError("minio unavailable")

    container.storage.upload_part_stream = unavailable_stream  # type: ignore[method-assign]
    failed = client.put(
        "/api/v1/files/upload-part",
        headers={"X-Upload-Part-Reference": reference},
        content=b"abc",
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "Upload part service unavailable"
    event = container.audit.events[-1]
    assert event.operation == "file.upload_part.stream"
    assert event.result == "FAILURE"
    assert event.error_code == "UPLOAD_PART_TRANSFER_FAILED"


@pytest.mark.asyncio
async def test_expired_upload_session_and_reference_fail_closed(
    container: Container, client: TestClient
) -> None:
    context = _context()
    initialized = await _initialize(container, context, 3)
    resource_id = str(initialized["resource"]["resource_id"])
    upload_id = str(initialized["upload_session_id"])
    key = (context.tenant_id, context.biz_domain, upload_id)
    container.state.file_uploads[key].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(InvalidStateTransition, match="expired"):
        await container.entry.use_cases.create_upload_part_references(
            context,
            {"resource_id": resource_id, "upload_session_id": upload_id, "parts": [1]},
        )
    assert container.state.file_uploads[key].status is UploadSessionStatus.EXPIRED

    active = await _initialize(container, context, 3)
    active_resource = str(active["resource"]["resource_id"])
    active_upload = str(active["upload_session_id"])
    references = await container.entry.use_cases.create_upload_part_references(
        context,
        {"resource_id": active_resource, "upload_session_id": active_upload, "parts": [1]},
    )
    reference = str(references["parts"][0]["upload_reference"])
    grants = container.entry.use_cases.upload_part_grants
    assert grants is not None and hasattr(grants, "grants")
    grants.grants[reference] = replace(  # type: ignore[attr-defined]
        grants.grants[reference],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),  # type: ignore[attr-defined]
    )
    assert (
        client.put(
            "/api/v1/files/upload-part",
            headers={"X-Upload-Part-Reference": reference},
            content=b"abc",
        ).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_version_create_complete_switch_delete_and_current_protection(
    container: Container,
) -> None:
    context = _context()
    resource_id, v1_id = await _create_available(container, context, b"version-one")
    created = await container.entry.use_cases.create_version_upload(
        context,
        {
            "resource_id": resource_id,
            "mime_type": "application/octet-stream",
            "size_bytes": len(b"version-two"),
        },
    )
    v2_id = str(created["version"]["version_id"])
    upload_id = str(created["upload_session_id"])
    etag = await _put_part(container, context, resource_id, upload_id, b"version-two")
    completed = await container.entry.use_cases.complete_upload(
        context,
        {
            "resource_id": resource_id,
            "upload_id": upload_id,
            "parts": [{"part_number": 1, "etag": etag}],
            "checksum": hashlib.sha256(b"version-two").hexdigest(),
        },
    )
    assert completed["version"]["status"] == FileResourceStatus.AVAILABLE.value

    switched = await container.entry.use_cases.switch_current_version(
        context, {"resource_id": resource_id, "version_id": v2_id}
    )
    assert switched["resource"]["current_version_id"] == v2_id
    assert (
        await container.entry.use_cases.switch_current_version(
            context, {"resource_id": resource_id, "version_id": v2_id}
        )
    ) == switched
    with pytest.raises(ValueError, match="Current version"):
        await container.entry.use_cases.delete_version(
            context, {"resource_id": resource_id, "version_id": v2_id}
        )
    deleted = await container.entry.use_cases.delete_version(
        context, {"resource_id": resource_id, "version_id": v1_id}
    )
    assert deleted["version"]["status"] == FileResourceStatus.DELETED.value


@pytest.mark.asyncio
async def test_aborting_new_version_preserves_available_current_version(
    container: Container,
) -> None:
    context = _context()
    resource_id, v1_id = await _create_available(container, context, b"stable-version")
    created = await container.entry.use_cases.create_version_upload(
        context,
        {
            "resource_id": resource_id,
            "mime_type": "application/octet-stream",
            "size_bytes": 8,
        },
    )
    v2_id = str(created["version"]["version_id"])
    upload_id = str(created["upload_session_id"])
    result = await container.entry.use_cases.abort_upload(
        context, {"resource_id": resource_id, "upload_id": upload_id}
    )
    version = await container.entry.use_cases.file_versions.get_by_scope_and_id(
        context.tenant_id, context.biz_domain, v2_id
    )
    upload = container.state.file_uploads[(context.tenant_id, context.biz_domain, upload_id)]
    assert result["resource"]["status"] == FileResourceStatus.AVAILABLE.value
    assert result["resource"]["current_version_id"] == v1_id
    assert version is not None and version.status is FileResourceStatus.FAILED
    assert upload.status is UploadSessionStatus.ABORTED


@pytest.mark.asyncio
async def test_tenant_and_business_domain_isolate_uploads_and_versions(
    container: Container,
) -> None:
    owner = _context()
    resource_id, version_id = await _create_available(container, owner, b"scoped")

    for foreign in (
        _context(tenant_id="other-tenant"),
        _context(biz_domain="other-domain"),
    ):
        with pytest.raises(FileResourceNotFound):
            await container.entry.use_cases.switch_current_version(
                foreign, {"resource_id": resource_id, "version_id": version_id}
            )
        with pytest.raises(FileResourceNotFound):
            await container.entry.use_cases.processor_input_reference(
                foreign, resource_id, version_id
            )


@pytest.mark.asyncio
async def test_file_delete_failure_is_failed_and_reconciled(container: Container) -> None:
    context = _context()
    resource_id, _ = await _create_available(container, context, b"delete-me")

    async def unavailable_delete(object_key: str) -> None:
        del object_key
        raise RuntimeError("minio unavailable")

    container.storage.delete = unavailable_delete  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="minio"):
        await container.entry.use_cases.delete_file(context, {"resource_id": resource_id})
    resource = container.state.files[(context.tenant_id, context.biz_domain, resource_id)]
    assert resource.status is FileResourceStatus.FAILED
    pending = await container.reconciliation.list_pending("FILE_DELETE_PENDING")
    assert pending and pending[0][1]["resource_id"] == resource_id


@pytest.mark.asyncio
async def test_file_delete_removes_all_version_objects_and_is_idempotent(
    container: Container,
) -> None:
    context = _context()
    resource_id, version_id = await _create_available(container, context, b"delete-success")
    version = await container.entry.use_cases.file_versions.get_by_scope_and_id(
        context.tenant_id, context.biz_domain, version_id
    )
    assert version is not None and await container.storage.exists(version.object_key)

    deleted = await container.entry.use_cases.delete_file(context, {"resource_id": resource_id})
    repeated = await container.entry.use_cases.delete_file(context, {"resource_id": resource_id})
    deleted_version = await container.entry.use_cases.file_versions.get_by_scope_and_id(
        context.tenant_id, context.biz_domain, version_id
    )
    assert deleted == repeated
    assert deleted["resource"]["status"] == FileResourceStatus.DELETED.value
    assert deleted_version is not None
    assert deleted_version.status is FileResourceStatus.DELETED
    assert not await container.storage.exists(version.object_key)


@pytest.mark.asyncio
async def test_file_delete_aborts_in_progress_version_upload(container: Container) -> None:
    context = _context()
    resource_id, _ = await _create_available(container, context, b"stable")
    created = await container.entry.use_cases.create_version_upload(
        context,
        {
            "resource_id": resource_id,
            "mime_type": "application/octet-stream",
            "size_bytes": 8,
        },
    )
    upload_id = str(created["upload_session_id"])
    upload_key = (context.tenant_id, context.biz_domain, upload_id)
    provider_upload_id = container.state.file_uploads[upload_key].provider_upload_id
    assert provider_upload_id in container.storage.multipart

    result = await container.entry.use_cases.delete_file(context, {"resource_id": resource_id})

    assert result["resource"]["status"] == FileResourceStatus.DELETED.value
    assert container.state.file_uploads[upload_key].status is UploadSessionStatus.ABORTED
    assert provider_upload_id not in container.storage.multipart
    versions = await container.entry.use_cases.file_versions.list_by_scope_and_resource(
        context.tenant_id, context.biz_domain, resource_id
    )
    assert versions and all(item.status is FileResourceStatus.DELETED for item in versions)


@pytest.mark.asyncio
async def test_version_delete_failure_records_reconciliation(container: Container) -> None:
    context = _context()
    resource_id, v1_id = await _create_available(container, context, b"version-delete")
    created = await container.entry.use_cases.create_version_upload(
        context,
        {
            "resource_id": resource_id,
            "mime_type": "application/octet-stream",
            "size_bytes": 2,
        },
    )
    v2_id = str(created["version"]["version_id"])
    upload_id = str(created["upload_session_id"])
    etag = await _put_part(container, context, resource_id, upload_id, b"v2")
    await container.entry.use_cases.complete_upload(
        context,
        {
            "resource_id": resource_id,
            "upload_id": upload_id,
            "parts": [{"part_number": 1, "etag": etag}],
            "checksum": hashlib.sha256(b"v2").hexdigest(),
        },
    )
    await container.entry.use_cases.switch_current_version(
        context, {"resource_id": resource_id, "version_id": v2_id}
    )

    async def unavailable_delete(object_key: str) -> None:
        del object_key
        raise RuntimeError("minio delete unavailable")

    container.storage.delete = unavailable_delete  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="delete"):
        await container.entry.use_cases.delete_version(
            context, {"resource_id": resource_id, "version_id": v1_id}
        )
    failed = await container.entry.use_cases.file_versions.get_by_scope_and_id(
        context.tenant_id, context.biz_domain, v1_id
    )
    pending = await container.reconciliation.list_pending("FILE_DELETE_PENDING")
    assert failed is not None and failed.status is FileResourceStatus.FAILED
    assert pending and pending[0][1]["version_id"] == v1_id


@pytest.mark.asyncio
async def test_minio_complete_failure_never_marks_resource_available(container: Container) -> None:
    context = _context()
    content = b"incomplete"
    initialized = await _initialize(container, context, len(content))
    resource_id = str(initialized["resource"]["resource_id"])
    upload_id = str(initialized["upload_session_id"])
    etag = await _put_part(container, context, resource_id, upload_id, content)

    async def unavailable_complete(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("minio unavailable")

    container.storage.complete_multipart_upload = unavailable_complete  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="minio"):
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": resource_id,
                "upload_id": upload_id,
                "parts": [{"part_number": 1, "etag": etag}],
                "checksum": hashlib.sha256(content).hexdigest(),
            },
        )
    resource = container.state.files[(context.tenant_id, context.biz_domain, resource_id)]
    assert resource.status is FileResourceStatus.FAILED


@pytest.mark.asyncio
async def test_processor_input_contract_is_opaque(container: Container) -> None:
    context = _context()
    resource_id, version_id = await _create_available(container, context, b"processor")
    reference = await container.entry.use_cases.processor_input_reference(
        context, resource_id, version_id
    )
    payload = asdict(reference)
    assert set(payload) == {
        "resource_id",
        "version_id",
        "tenant_id",
        "biz_domain",
        "mime_type",
        "checksum",
        "storage_reference",
    }
    assert reference.storage_reference.startswith("file-resource:")
    assert "object_key" not in payload
    assert "bucket" not in payload
    assert "minio" not in str(payload).lower()


@pytest.mark.asyncio
async def test_phase31_control_plane_rejects_mismatched_and_unavailable_references(
    container: Container,
) -> None:
    context = _context()
    first = await _initialize(container, context, 3)
    second = await _initialize(container, context, 3)
    first_resource = str(first["resource"]["resource_id"])
    first_upload = str(first["upload_session_id"])
    second_upload = str(second["upload_session_id"])

    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.create_upload_part_references(
            context,
            {
                "resource_id": first_resource,
                "upload_session_id": second_upload,
                "parts": [1],
            },
        )
    original_grants = container.entry.use_cases.upload_part_grants
    container.entry.use_cases.upload_part_grants = None
    with pytest.raises(RuntimeError, match="unavailable"):
        await container.entry.use_cases.create_upload_part_references(
            context,
            {
                "resource_id": first_resource,
                "upload_session_id": first_upload,
                "parts": [1],
            },
        )
    container.entry.use_cases.upload_part_grants = original_grants
    references = await container.entry.use_cases.create_upload_part_references(
        context,
        {
            "resource_id": first_resource,
            "upload_session_id": first_upload,
            "parts": [1, 2],
        },
    )
    first_reference = str(references["parts"][0]["upload_reference"])
    _, first_etag = await container.entry.use_cases.consume_upload_part(first_reference, b"abc")
    with pytest.raises(ValueError, match="uploaded parts"):
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": first_resource,
                "upload_id": first_upload,
                "parts": [{"part_number": 1, "etag": first_etag}],
                "checksum": hashlib.sha256(b"abc").hexdigest(),
            },
        )
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": first_resource,
                "upload_id": second_upload,
                "parts": [{"part_number": 1, "etag": "mismatched"}],
                "checksum": "0" * 64,
            },
        )

    first_available, first_version = await _create_available(container, context, b"first")
    _second_available, second_version = await _create_available(container, context, b"second")
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.processor_input_reference(
            context, first_available, second_version
        )
    first_key = (context.tenant_id, context.biz_domain, first_available)
    container.state.files[first_key].current_version_id = None
    with pytest.raises(FileResourceNotFound, match="Current"):
        await container.entry.use_cases.processor_input_reference(context, first_available)
    container.state.files[first_key].current_version_id = first_version
    version_key = (context.tenant_id, context.biz_domain, first_available, 1)
    container.state.file_versions[version_key].checksum = None
    with pytest.raises(ValueError, match="checksum"):
        await container.entry.use_cases.processor_input_reference(
            context, first_available, first_version
        )
