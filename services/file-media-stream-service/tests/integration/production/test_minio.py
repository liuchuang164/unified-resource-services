import os

import pytest
from minio import Minio
from minio.error import S3Error

from file_media_stream_service.adapters.object_storage.minio import (
    MinioObjectStorage,
    create_minio_client,
)

pytestmark = pytest.mark.production_integration
BUCKET = "file-media-stream"


@pytest.mark.asyncio
async def test_upload_multipart_metadata_range_urls_delete_and_abort(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = create_minio_client(
        "localhost:59000", "fms_local", "fms_local_only_secret", secure=False
    )
    storage = MinioObjectStorage(client, BUCKET, upload_ttl_seconds=60, download_ttl_seconds=60)
    key = "tenant-a/legal/res-minio/v1/data.bin"
    assert (await storage.initialize_upload(key, "application/octet-stream", 6_000_000)).startswith(
        "minio_upload_"
    )
    upload_url = await storage.presigned_upload_url(key)
    assert "X-Amz-Signature=" in upload_url
    upload = await storage.begin_multipart(key, "text/plain")
    data = os.urandom(6_000_000)

    async def chunks():
        for offset in range(0, len(data), 64 * 1024):
            yield data[offset : offset + 64 * 1024]

    etag = await storage.upload_part_stream(key, upload.upload_id, 1, chunks(), len(data))
    metadata = await storage.complete_multipart(upload, [(1, etag)])
    assert metadata.size_bytes == len(data)
    assert metadata.content_type == "text/plain"
    assert await storage.exists(key)
    assert await storage.read_range(key, 10, 20) == data[10:30]
    download_url = await storage.presigned_download_url(key)
    assert "X-Amz-Signature=" in download_url
    await storage.delete(key)
    assert not await storage.exists(key)
    await storage.abort_upload(key)
    interrupted = await storage.begin_multipart(key)
    await storage.abort_multipart(interrupted)
    assert await storage.check()
    assert upload_url not in caplog.text
    assert download_url not in caplog.text
    assert "fms_local_only_secret" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_key_and_permission_denial() -> None:
    client = Minio("localhost:59000", access_key="bad", secret_key="bad-secret", secure=False)
    denied = MinioObjectStorage(client, BUCKET)
    with pytest.raises(S3Error):
        await denied.get_metadata("tenant-a/legal/missing")
    storage = MinioObjectStorage(
        create_minio_client("localhost:59000", "fms_local", "fms_local_only_secret", secure=False),
        BUCKET,
    )
    with pytest.raises(ValueError):
        await storage.initialize_upload("../escape", "text/plain", 1)
