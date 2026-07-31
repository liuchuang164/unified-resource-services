from pathlib import PurePosixPath
from typing import ClassVar


class MetadataSafetyValidator:
    """Phase 3 metadata-only scanner boundary; no malware engine is embedded."""

    _EXTENSIONS: ClassVar[dict[str, set[str]]] = {
        "application/pdf": {".pdf"},
        "text/plain": {".txt"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "audio/mpeg": {".mp3"},
        "audio/wav": {".wav"},
        "video/mp4": {".mp4"},
        "application/octet-stream": set(),
    }

    async def validate_metadata(
        self, filename: str, mime_type: str, size_bytes: int, checksum: str
    ) -> None:
        allowed = self._EXTENSIONS.get(mime_type)
        if allowed is None:
            raise ValueError("MIME type is not allowed")
        suffix = PurePosixPath(filename).suffix.lower()
        if allowed and suffix not in allowed:
            raise ValueError("Filename extension does not match MIME type")
        if size_bytes < 0 or len(checksum) != 64:
            raise ValueError("File metadata is invalid")
