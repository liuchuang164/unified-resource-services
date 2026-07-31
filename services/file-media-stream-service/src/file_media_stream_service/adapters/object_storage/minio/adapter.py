import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from minio import Minio
from minio.error import S3Error

from file_media_stream_service.application.ports.protocols import (
    StoredObjectMetadata,
    UploadHandle,
)


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    size_bytes: int
    etag: str
    content_type: str | None


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    upload_id: str
    object_key: str


class MinioObjectStorage:
    """Tenant-safe object operations for server-generated object keys."""

    def __init__(
        self,
        client: Minio,
        bucket: str,
        *,
        upload_ttl_seconds: int = 900,
        download_ttl_seconds: int = 300,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._upload_ttl = timedelta(seconds=upload_ttl_seconds)
        self._download_ttl = timedelta(seconds=download_ttl_seconds)

    async def initialize_upload(self, object_key: str, mime_type: str, size_bytes: int) -> str:
        self._validate_key(object_key)
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        # The reference is deliberately opaque: presigned URLs never enter domain state.
        digest = hashlib.sha256(f"{object_key}\0{mime_type}\0{size_bytes}".encode()).hexdigest()[
            :32
        ]
        return f"minio_upload_{digest}"

    async def presigned_upload_url(self, object_key: str) -> str:
        self._validate_key(object_key)
        return await asyncio.to_thread(
            self._client.presigned_put_object,
            self._bucket,
            object_key,
            self._upload_ttl,
        )

    async def begin_multipart(self, object_key: str) -> MultipartUpload:
        self._validate_key(object_key)
        upload_id = await asyncio.to_thread(
            self._client._create_multipart_upload,
            self._bucket,
            object_key,
            {},
        )
        return MultipartUpload(upload_id=upload_id, object_key=object_key)

    async def create_multipart_upload(self, object_key: str) -> UploadHandle:
        upload = await self.begin_multipart(object_key)
        return UploadHandle(upload.upload_id)

    async def upload_part(
        self,
        upload: MultipartUpload,
        part_number: int,
        data: bytes,
    ) -> str:
        self._validate_key(upload.object_key)
        if part_number < 1 or part_number > 10_000:
            raise ValueError("part_number must be between 1 and 10000")
        etag = await asyncio.to_thread(
            self._client._upload_part,
            self._bucket,
            upload.object_key,
            data,
            None,
            upload.upload_id,
            part_number,
        )
        return str(etag)

    async def complete_multipart(
        self,
        upload: MultipartUpload,
        parts: Iterable[tuple[int, str]],
    ) -> StoredObjectMetadata:
        from minio.datatypes import Part

        self._validate_key(upload.object_key)
        normalized = [Part(number, etag) for number, etag in sorted(parts)]
        if not normalized:
            raise ValueError("at least one multipart part is required")
        await asyncio.to_thread(
            self._client._complete_multipart_upload,
            self._bucket,
            upload.object_key,
            upload.upload_id,
            normalized,
            None,
        )
        return await self.get_metadata(upload.object_key)

    async def complete_multipart_upload(
        self, object_key: str, provider_upload_id: str, parts: tuple[tuple[int, str], ...]
    ) -> StoredObjectMetadata:
        await self.complete_multipart(MultipartUpload(provider_upload_id, object_key), parts)
        return await self.get_metadata(object_key)

    async def abort_multipart(self, upload: MultipartUpload) -> None:
        self._validate_key(upload.object_key)
        await asyncio.to_thread(
            self._client._abort_multipart_upload,
            self._bucket,
            upload.object_key,
            upload.upload_id,
        )

    async def abort_multipart_upload(self, object_key: str, provider_upload_id: str) -> None:
        await self.abort_multipart(MultipartUpload(provider_upload_id, object_key))

    async def abort_upload(self, object_key: str) -> None:
        self._validate_key(object_key)
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, object_key)
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchObject"}:
                raise

    async def get_metadata(self, object_key: str) -> StoredObjectMetadata:
        self._validate_key(object_key)
        value = await asyncio.to_thread(self._client.stat_object, self._bucket, object_key)
        return StoredObjectMetadata(
            size_bytes=int(value.size or 0),
            checksum=await self._sha256(object_key),
            content_type=value.content_type,
        )

    async def presigned_download_url(self, object_key: str) -> str:
        self._validate_key(object_key)
        return await asyncio.to_thread(
            self._client.presigned_get_object,
            self._bucket,
            object_key,
            self._download_ttl,
        )

    async def create_download_url(self, object_key: str) -> tuple[str, datetime]:
        url = await self.presigned_download_url(object_key)
        return (url, datetime.now(UTC) + self._download_ttl)

    async def read_range(self, object_key: str, offset: int, length: int) -> bytes:
        self._validate_key(object_key)
        if offset < 0 or length <= 0:
            raise ValueError("range offset and length are invalid")
        response = await asyncio.to_thread(
            self._client.get_object,
            self._bucket,
            object_key,
            offset,
            length,
        )
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def _stream_range(
        self, object_key: str, offset: int, length: int
    ) -> AsyncIterator[bytes]:
        self._validate_key(object_key)
        if offset < 0 or length <= 0:
            raise ValueError("range offset and length are invalid")
        response = await asyncio.to_thread(
            self._client.get_object, self._bucket, object_key, offset, length
        )
        remaining = length
        try:
            while remaining:
                chunk = await asyncio.to_thread(response.read, min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            response.close()
            response.release_conn()

    def stream_range(self, object_key: str, offset: int, length: int) -> AsyncIterator[bytes]:
        return self._stream_range(object_key, offset, length)

    async def delete(self, object_key: str) -> None:
        self._validate_key(object_key)
        await asyncio.to_thread(self._client.remove_object, self._bucket, object_key)

    async def exists(self, object_key: str) -> bool:
        try:
            await self.get_metadata(object_key)
            return True
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._client.bucket_exists, self._bucket)
            return True
        except Exception:
            return False

    async def check(self) -> bool:
        return await self.health()

    async def _sha256(self, object_key: str) -> str:
        response = await asyncio.to_thread(self._client.get_object, self._bucket, object_key)
        digest = hashlib.sha256()
        try:
            while chunk := await asyncio.to_thread(response.read, 64 * 1024):
                digest.update(chunk)
        finally:
            response.close()
            response.release_conn()
        return digest.hexdigest()

    @staticmethod
    def _validate_key(object_key: str) -> None:
        if (
            not object_key
            or object_key.startswith("/")
            or ".." in object_key.split("/")
            or "\\" in object_key
        ):
            raise ValueError("invalid server-generated object key")
