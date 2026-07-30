from __future__ import annotations

import json
from pathlib import PurePosixPath

from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.observability.metrics import metrics_registry


class MinIOContentValidator:
    _magic: dict[str, tuple[bytes, ...]] = {
        "application/pdf": (b"%PDF-",),
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/jpeg": (b"\xff\xd8\xff",),
        "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
        "audio/wav": (b"RIFF",),
        "video/mp4": (b"\x00\x00\x00",),
    }

    _extension_types: dict[str, set[str]] = {
        ".pdf": {"application/pdf"},
        ".png": {"image/png"},
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
        ".txt": {"text/plain"},
        ".json": {"application/json"},
        ".mp3": {"audio/mpeg"},
        ".wav": {"audio/wav"},
        ".mp4": {"video/mp4"},
    }

    def __init__(
        self,
        *,
        allowed_content_types: set[str],
        allowed_extensions: set[str],
        max_object_size_bytes: int,
    ) -> None:
        self._allowed_content_types = allowed_content_types
        self._allowed_extensions = allowed_extensions
        self._max_object_size_bytes = max_object_size_bytes

    def validate(
        self, *, content: bytes, filename: str, content_type: str, declared_size: int
    ) -> None:
        if (
            len(content) > self._max_object_size_bytes
            or declared_size > self._max_object_size_bytes
        ):
            metrics_registry.increment("minio_object_too_large_total")
            raise DataControlError("OBJECT_TOO_LARGE")
        if len(content) != declared_size:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "declared object size does not match")
        self.validate_metadata(
            filename=filename, content_type=content_type, size_bytes=len(content)
        )
        self.validate_magic(content=content, content_type=content_type)

    def validate_metadata(self, *, filename: str, content_type: str, size_bytes: int) -> None:
        extension = PurePosixPath(filename).suffix.lower()
        if size_bytes > self._max_object_size_bytes:
            metrics_registry.increment("minio_object_too_large_total")
            raise DataControlError("OBJECT_TOO_LARGE")
        if content_type not in self._allowed_content_types:
            metrics_registry.increment("minio_content_type_rejected_total")
            raise DataControlError("CONTENT_TYPE_NOT_ALLOWED")
        if extension not in self._allowed_extensions:
            metrics_registry.increment("minio_content_type_rejected_total")
            raise DataControlError("CONTENT_TYPE_NOT_ALLOWED")
        if content_type not in self._extension_types.get(extension, set()):
            metrics_registry.increment("minio_content_type_rejected_total")
            raise DataControlError("CONTENT_TYPE_NOT_ALLOWED")

    def validate_magic(self, *, content: bytes, content_type: str) -> None:
        if content_type in {"text/plain"}:
            content.decode("utf-8")
            return
        if content_type == "application/json":
            json.loads(content.decode("utf-8"))
            return
        prefixes = self._magic.get(content_type)
        if not prefixes or not any(content.startswith(prefix) for prefix in prefixes):
            metrics_registry.increment("minio_content_type_rejected_total")
            raise DataControlError("CONTENT_TYPE_NOT_ALLOWED")
