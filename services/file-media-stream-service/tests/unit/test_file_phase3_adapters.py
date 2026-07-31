import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from file_media_stream_service.adapters.coordination.redis import RedisRangeAccessGrantStore
from file_media_stream_service.adapters.file_verification import MetadataSafetyValidator
from file_media_stream_service.adapters.object_storage import InMemoryObjectStorage
from file_media_stream_service.adapters.object_storage.minio import MinioObjectStorage
from file_media_stream_service.adapters.production_boundaries import (
    ExternalSecurityBoundary,
    StructuredEventBus,
    UnavailableMediaProvider,
    UnavailableMediaServer,
    UnavailableProcessor,
)
from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.domain.entities import RangeAccessGrant
from file_media_stream_service.domain.exceptions import PermissionDenied, Unauthenticated


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, **_: Any) -> bool:
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, count: int, key: str) -> str | None:
        del script, count
        return self.values.pop(key, None)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.position = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.content)
        chunk = self.content[self.position : self.position + size]
        self.position += len(chunk)
        return chunk

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class FakeMinioClient:
    def __init__(self) -> None:
        self.content = b"abcdef"
        self.removed: list[str] = []

    def _create_multipart_upload(self, bucket: str, key: str, headers: dict[str, str]) -> str:
        del bucket, key, headers
        return "provider-upload"

    def _complete_multipart_upload(self, *args: Any) -> None:
        del args

    def _abort_multipart_upload(self, *args: Any) -> None:
        del args

    def stat_object(self, bucket: str, key: str) -> Any:
        del bucket, key
        return type("Metadata", (), {"size": len(self.content), "content_type": "text/plain"})()

    def get_object(self, bucket: str, key: str, offset: int = 0, length: int = 0) -> FakeResponse:
        del bucket, key
        content = self.content[offset : offset + length] if length else self.content
        return FakeResponse(content)

    def presigned_get_object(self, bucket: str, key: str, expires: timedelta) -> str:
        del bucket, key, expires
        return "https://minio.invalid/signed"

    def presigned_put_object(self, bucket: str, key: str, expires: timedelta) -> str:
        del bucket, key, expires
        return "https://minio.invalid/upload"

    def remove_object(self, bucket: str, key: str) -> None:
        del bucket
        self.removed.append(key)

    def bucket_exists(self, bucket: str) -> bool:
        del bucket
        return True


@pytest.mark.asyncio
async def test_metadata_safety_validator_rejects_unsafe_metadata() -> None:
    validator = MetadataSafetyValidator()
    checksum = "a" * 64
    await validator.validate_metadata("safe.pdf", "application/pdf", 1, checksum)
    with pytest.raises(ValueError, match="MIME"):
        await validator.validate_metadata("safe.exe", "bad/type", 1, checksum)
    with pytest.raises(ValueError, match="extension"):
        await validator.validate_metadata("safe.txt", "application/pdf", 1, checksum)
    with pytest.raises(ValueError, match="metadata"):
        await validator.validate_metadata("safe.pdf", "application/pdf", -1, checksum)


@pytest.mark.asyncio
async def test_in_memory_multipart_storage_boundaries() -> None:
    storage = InMemoryObjectStorage()
    await storage.initialize_upload("safe/key", "text/plain", 3)
    handle = await storage.create_multipart_upload("safe/key")
    etag = await storage.upload_part(handle.provider_upload_id, 1, b"abc")
    metadata = await storage.complete_multipart_upload(
        "safe/key", handle.provider_upload_id, ((1, etag),)
    )
    assert metadata.checksum == hashlib.sha256(b"abc").hexdigest()
    assert await storage.exists("safe/key")
    assert await storage.health()
    assert await storage.check()
    await storage.delete("safe/key")
    assert not await storage.exists("safe/key")

    abandoned = await storage.create_multipart_upload("safe/abandoned")
    await storage.abort_multipart_upload("safe/abandoned", abandoned.provider_upload_id)
    await storage.abort_upload("safe/abandoned")
    with pytest.raises(FileNotFoundError):
        await storage.get_metadata("missing")
    with pytest.raises(FileNotFoundError):
        await storage.create_download_url("missing")
    with pytest.raises(RuntimeError, match="does not match"):
        await storage.complete_multipart_upload("wrong/key", "missing", ((1, "etag"),))
    missing_stream = storage.stream_range("missing", 0, 1)
    with pytest.raises(FileNotFoundError):
        await anext(missing_stream)


@pytest.mark.asyncio
async def test_redis_range_reference_is_atomic_and_one_time() -> None:
    redis = FakeRedis()
    store = RedisRangeAccessGrantStore(redis)  # type: ignore[arg-type]
    grant = RangeAccessGrant(
        reference_id="secret-reference",
        resource_id="resource-1",
        tenant_id="tenant-1",
        biz_domain="legal",
        caller_id="service-1",
        caller_type="service",
        request_id="request-1",
        trace_id="trace-1",
        offset=3,
        length=4,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    await store.issue(grant)
    assert "secret-reference" not in next(iter(redis.values))
    consumed = await store.consume(grant.reference_id)
    assert consumed == grant
    assert await store.consume(grant.reference_id) is None


@pytest.mark.asyncio
async def test_minio_phase3_adapter_operations() -> None:
    client = FakeMinioClient()
    storage = MinioObjectStorage(client, "bucket")  # type: ignore[arg-type]
    assert (await storage.initialize_upload("safe/key", "text/plain", 6)).startswith(
        "minio_upload_"
    )
    assert await storage.presigned_upload_url("safe/key") == "https://minio.invalid/upload"
    handle = await storage.create_multipart_upload("safe/key")
    assert handle.provider_upload_id == "provider-upload"
    metadata = await storage.complete_multipart_upload(
        "safe/key", handle.provider_upload_id, ((1, "etag"),)
    )
    assert metadata.size_bytes == 6
    assert metadata.checksum == hashlib.sha256(b"abcdef").hexdigest()
    await storage.abort_multipart_upload("safe/key", handle.provider_upload_id)
    url, expires_at = await storage.create_download_url("safe/key")
    assert url == "https://minio.invalid/signed"
    assert expires_at > datetime.now(UTC)
    stream = storage.stream_range("safe/key", 1, 3)
    assert b"".join([chunk async for chunk in stream]) == b"bcd"
    assert await storage.read_range("safe/key", 2, 2) == b"cd"
    assert await storage.exists("safe/key")
    assert await storage.health()
    await storage.delete("safe/key")
    assert client.removed == ["safe/key"]


@pytest.mark.asyncio
async def test_production_boundaries_remain_fail_closed() -> None:
    context = RequestContext(
        request_id="request",
        trace_id="trace",
        tenant_id="tenant",
        biz_domain="legal",
        caller_type="agent",
        caller_id="agent",
        agent_id="agent",
        tool_call_id="tool",
        capability_token="capability",
        nonce="nonce",
    )
    security = ExternalSecurityBoundary()
    await security.verify(context)
    incomplete = context.model_copy(update={"caller_id": ""})
    with pytest.raises(Unauthenticated):
        await security.verify(incomplete)
    with pytest.raises(Unauthenticated):
        await security.verify_capability(context, "file.read_range")
    await security.verify_capability(
        context.model_copy(update={"caller_type": "service"}), "file.read_range"
    )
    with pytest.raises(PermissionDenied):
        await security.authorize(context, "file.read_range", "resource")
    with pytest.raises(RuntimeError):
        await UnavailableMediaServer().close_session("session")
    with pytest.raises(RuntimeError):
        await UnavailableMediaServer().create_session("WEBRTC", "INGRESS", datetime.now(UTC))
    with pytest.raises(RuntimeError):
        await UnavailableMediaProvider().create_stream_endpoint(
            "tenant", "legal", "session", "WEBRTC", "INGRESS", datetime.now(UTC), 1
        )
    with pytest.raises(RuntimeError):
        await UnavailableMediaProvider().start_stream("session", 1)
    with pytest.raises(RuntimeError):
        await UnavailableMediaProvider().stop_stream("session", 1)
    status = await UnavailableMediaProvider().get_stream_status("session", 1)
    assert not status.exists and not status.connected
    assert not await UnavailableMediaProvider().health_check()
    with pytest.raises(RuntimeError):
        await UnavailableProcessor().submit("processor", "resource", {})
    await StructuredEventBus().publish("file.safe", {"resource_id": "resource", "token": "hidden"})
