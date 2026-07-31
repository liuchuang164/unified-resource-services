import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from file_media_stream_service.application.ports.protocols import (
    StoredObjectMetadata,
    UploadHandle,
)


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, tuple[str, int]] = {}
        self.multipart: dict[str, dict[int, bytes]] = {}
        self.multipart_keys: dict[str, str] = {}
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.download_ttl_seconds = 300

    async def initialize_upload(self, object_key: str, mime_type: str, size_bytes: int) -> str:
        self.uploads[object_key] = (mime_type, size_bytes)
        digest = hashlib.sha256(object_key.encode()).hexdigest()[:24]
        return f"upload_ref_{digest}"

    async def create_multipart_upload(self, object_key: str) -> UploadHandle:
        provider_upload_id = "provider_" + hashlib.sha256(object_key.encode()).hexdigest()[:24]
        self.multipart[provider_upload_id] = {}
        self.multipart_keys[provider_upload_id] = object_key
        return UploadHandle(provider_upload_id)

    async def upload_part(self, provider_upload_id: str, part_number: int, content: bytes) -> str:
        self.multipart[provider_upload_id][part_number] = bytes(content)
        return hashlib.md5(content, usedforsecurity=False).hexdigest()

    async def complete_multipart_upload(
        self, object_key: str, provider_upload_id: str, parts: tuple[tuple[int, str], ...]
    ) -> StoredObjectMetadata:
        if self.multipart_keys.get(provider_upload_id) != object_key:
            raise RuntimeError("Upload session does not match object")
        content = b"".join(self.multipart[provider_upload_id][number] for number, _ in parts)
        self.objects[object_key] = content
        if object_key in self.uploads:
            self.content_types[object_key] = self.uploads[object_key][0]
        self.multipart.pop(provider_upload_id, None)
        self.multipart_keys.pop(provider_upload_id, None)
        return await self.get_metadata(object_key)

    async def abort_multipart_upload(self, object_key: str, provider_upload_id: str) -> None:
        if self.multipart_keys.get(provider_upload_id) == object_key:
            self.multipart.pop(provider_upload_id, None)
            self.multipart_keys.pop(provider_upload_id, None)

    async def abort_upload(self, object_key: str) -> None:
        self.uploads.pop(object_key, None)
        self.objects.pop(object_key, None)

    async def get_metadata(self, object_key: str) -> StoredObjectMetadata:
        if object_key not in self.objects:
            raise FileNotFoundError("Stored object does not exist")
        content = self.objects[object_key]
        return StoredObjectMetadata(
            len(content),
            hashlib.sha256(content).hexdigest(),
            self.content_types.get(object_key),
        )

    async def create_download_url(self, object_key: str) -> tuple[str, datetime]:
        if object_key not in self.objects:
            raise FileNotFoundError("Stored object does not exist")
        expires_at = datetime.now(UTC) + timedelta(seconds=self.download_ttl_seconds)
        reference = hashlib.sha256(f"{object_key}:{expires_at.isoformat()}".encode()).hexdigest()
        return (f"https://object-storage.invalid/download/{reference}", expires_at)

    async def put_object(self, object_key: str, content: bytes, mime_type: str) -> None:
        self.objects[object_key] = bytes(content)
        self.content_types[object_key] = mime_type

    async def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    async def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    async def health(self) -> bool:
        return True

    async def check(self) -> bool:
        return True

    async def _range_chunks(
        self, object_key: str, offset: int, length: int
    ) -> AsyncIterator[bytes]:
        if object_key not in self.objects:
            raise FileNotFoundError("Stored object does not exist")
        content = self.objects[object_key][offset : offset + length]
        chunk_size = 64 * 1024
        for position in range(0, len(content), chunk_size):
            yield content[position : position + chunk_size]

    def stream_range(self, object_key: str, offset: int, length: int) -> AsyncIterator[bytes]:
        return self._range_chunks(object_key, offset, length)
