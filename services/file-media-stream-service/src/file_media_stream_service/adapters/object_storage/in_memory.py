import hashlib


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, tuple[str, int]] = {}

    async def initialize_upload(self, object_key: str, mime_type: str, size_bytes: int) -> str:
        self.uploads[object_key] = (mime_type, size_bytes)
        digest = hashlib.sha256(object_key.encode()).hexdigest()[:24]
        return f"upload_ref_{digest}"

    async def abort_upload(self, object_key: str) -> None:
        self.uploads.pop(object_key, None)
