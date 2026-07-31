import hashlib

import pytest
from fastapi.testclient import TestClient

from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.bootstrap import Container
from file_media_stream_service.domain.enums import FileResourceStatus
from file_media_stream_service.domain.exceptions import FileResourceNotFound


@pytest.mark.asyncio
async def test_file_lifecycle_and_one_time_range_reference(
    container: Container, client: TestClient
) -> None:
    context = RequestContext(
        request_id="phase3-request",
        trace_id="phase3-trace",
        tenant_id="dev-tenant",
        biz_domain="development",
        caller_type="service",
        caller_id="dev-service",
    )
    content = b"abcdef"
    initialized = await container.entry.use_cases.initialize_upload(
        context,
        {
            "filename": "sample.txt",
            "mime_type": "text/plain",
            "size_bytes": len(content),
            "owner_type": "case",
            "owner_id": "case-1",
        },
    )
    upload_id = initialized["upload_id"]
    upload = container.state.file_uploads[("dev-tenant", "development", upload_id)]
    etag = await container.storage.upload_part(upload.provider_upload_id, 1, content)
    completed = await container.entry.use_cases.complete_upload(
        context,
        {
            "resource_id": upload.resource_id,
            "upload_id": upload_id,
            "parts": [{"part_number": 1, "etag": etag}],
            "checksum": hashlib.sha256(content).hexdigest(),
        },
    )
    assert completed["resource"]["status"] == FileResourceStatus.AVAILABLE.value
    assert (
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": upload.resource_id,
                "upload_id": upload_id,
                "parts": [{"part_number": 1, "etag": etag}],
                "checksum": hashlib.sha256(content).hexdigest(),
            },
        )
    ) == completed
    with pytest.raises(ValueError, match="outside"):
        await container.entry.use_cases.issue_range_access(
            context, {"resource_id": upload.resource_id, "offset": 6, "length": 1}
        )

    reference = await container.entry.use_cases.issue_range_access(
        context, {"resource_id": upload.resource_id, "offset": 1, "length": 3}
    )
    assert set(reference) == {
        "reference_id",
        "resource_id",
        "offset",
        "length",
        "expires_at",
    }
    _, _, stream = await container.entry.use_cases.consume_range_access(reference["reference_id"])
    assert b"".join([chunk async for chunk in stream]) == b"bcd"
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.consume_range_access(reference["reference_id"])

    metadata = await container.entry.use_cases.get_metadata(
        context, {"resource_id": upload.resource_id}
    )
    assert metadata["versions"][0]["checksum"] == hashlib.sha256(content).hexdigest()
    download = await container.entry.use_cases.create_download_url(
        context, {"resource_id": upload.resource_id}
    )
    assert download["url"].startswith("https://object-storage.invalid/")

    endpoint_reference = await container.entry.use_cases.issue_range_access(
        context, {"resource_id": upload.resource_id, "offset": 2, "length": 2}
    )
    streamed = client.get(
        "/api/v1/files/range",
        headers={"X-Range-Access-Reference": endpoint_reference["reference_id"]},
    )
    assert streamed.status_code == 206
    assert streamed.content == b"cd"
    assert streamed.headers["content-range"] == "bytes 2-3/6"
    assert (
        client.get(
            "/api/v1/files/range",
            headers={"X-Range-Access-Reference": endpoint_reference["reference_id"]},
        ).status_code
        == 403
    )

    deleted = await container.entry.use_cases.delete_file(
        context, {"resource_id": upload.resource_id}
    )
    assert deleted["resource"]["status"] == FileResourceStatus.DELETED.value
    repeated = await container.entry.use_cases.delete_file(
        context, {"resource_id": upload.resource_id}
    )
    assert repeated == deleted


@pytest.mark.asyncio
async def test_abort_upload_is_idempotent(container: Container) -> None:
    context = RequestContext(
        request_id="abort-request",
        trace_id="abort-trace",
        tenant_id="dev-tenant",
        biz_domain="development",
        caller_type="service",
        caller_id="dev-service",
    )
    initialized = await container.entry.use_cases.initialize_upload(
        context,
        {
            "filename": "sample.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "owner_type": "case",
            "owner_id": "case-2",
        },
    )
    payload = {
        "resource_id": initialized["resource"]["resource_id"],
        "upload_id": initialized["upload_id"],
    }
    first = await container.entry.use_cases.abort_upload(context, payload)
    second = await container.entry.use_cases.abort_upload(context, payload)
    assert first["resource"]["status"] == FileResourceStatus.FAILED.value
    assert second["resource"]["status"] == FileResourceStatus.FAILED.value


@pytest.mark.asyncio
async def test_checksum_mismatch_marks_resource_failed(container: Container) -> None:
    context = RequestContext(
        request_id="mismatch-request",
        trace_id="mismatch-trace",
        tenant_id="dev-tenant",
        biz_domain="development",
        caller_type="service",
        caller_id="dev-service",
    )
    initialized = await container.entry.use_cases.initialize_upload(
        context,
        {
            "filename": "sample.txt",
            "mime_type": "text/plain",
            "size_bytes": 3,
            "owner_type": "case",
            "owner_id": "case-3",
        },
    )
    upload_id = initialized["upload_id"]
    upload = container.state.file_uploads[("dev-tenant", "development", upload_id)]
    etag = await container.storage.upload_part(upload.provider_upload_id, 1, b"abc")
    with pytest.raises(ValueError, match="metadata"):
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": upload.resource_id,
                "upload_id": upload_id,
                "parts": [{"part_number": 1, "etag": etag}],
                "checksum": "0" * 64,
            },
        )
    resource = container.state.files[("dev-tenant", "development", upload.resource_id)]
    assert resource.status is FileResourceStatus.FAILED


@pytest.mark.asyncio
async def test_file_data_plane_fail_closed_paths(container: Container) -> None:
    context = RequestContext(
        request_id="closed-request",
        trace_id="closed-trace",
        tenant_id="dev-tenant",
        biz_domain="development",
        caller_type="service",
        caller_id="dev-service",
    )
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.get_metadata(context, {"resource_id": "missing"})
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.abort_upload(
            context, {"resource_id": "missing", "upload_id": "missing"}
        )
    original_grants = container.entry.use_cases.range_grants
    container.entry.use_cases.range_grants = None
    with pytest.raises(FileResourceNotFound):
        await container.entry.use_cases.consume_range_access("missing")
    container.entry.use_cases.range_grants = original_grants


@pytest.mark.asyncio
async def test_post_storage_metadata_failure_records_reconciliation(
    container: Container,
) -> None:
    context = RequestContext(
        request_id="reconcile-request",
        trace_id="reconcile-trace",
        tenant_id="dev-tenant",
        biz_domain="development",
        caller_type="service",
        caller_id="dev-service",
    )
    content = b"xyz"
    initialized = await container.entry.use_cases.initialize_upload(
        context,
        {
            "filename": "sample.txt",
            "mime_type": "text/plain",
            "size_bytes": len(content),
            "owner_type": "case",
            "owner_id": "case-4",
        },
    )
    upload_id = initialized["upload_id"]
    upload = container.state.file_uploads[("dev-tenant", "development", upload_id)]
    etag = await container.storage.upload_part(upload.provider_upload_id, 1, content)

    async def unavailable_save(resource: object) -> None:
        del resource
        raise RuntimeError("postgres unavailable")

    container.entry.use_cases.files.save = unavailable_save  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="postgres"):
        await container.entry.use_cases.complete_upload(
            context,
            {
                "resource_id": upload.resource_id,
                "upload_id": upload_id,
                "parts": [{"part_number": 1, "etag": etag}],
                "checksum": hashlib.sha256(content).hexdigest(),
            },
        )
    pending = await container.reconciliation.list_pending("FILE_METADATA_SYNC_REQUIRED")
    assert pending[0][1]["resource_id"] == upload.resource_id


def test_binary_endpoint_does_not_embed_reference_in_url(client: TestClient) -> None:
    routes = {route.path for route in client.app.routes}
    assert "/api/v1/files/range" in routes
    assert all("{reference_id}" not in path for path in routes)
    gateway = client.app.state.container.gateway
    assert any(tool["name"] == "file.read_range" for tool in gateway.list_tools())
    assert gateway.get_schema("file.read_range")["additionalProperties"] is False
    assert gateway.get_schema("not-a-tool") is None
