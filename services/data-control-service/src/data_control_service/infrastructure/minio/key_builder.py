from __future__ import annotations

import hashlib
import posixpath
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

from data_control_service.domain.exceptions import DataControlError


class MinIOObjectKeyBuilder:
    _safe_segment = re.compile(r"^[A-Za-z0-9._-]+$")

    def safe_filename(self, filename: str) -> str:
        normalized = unicodedata.normalize("NFKC", filename or "")
        name = PureWindowsPath(PurePosixPath(normalized).name).name
        if not name or name in {".", ".."}:
            raise DataControlError("OBJECT_PATH_INVALID")
        lowered = normalized.lower()
        if (
            ".." in normalized
            or normalized.startswith(("/", "\\"))
            or re.match(r"^[a-zA-Z]:\\", normalized)
            or lowered.startswith(("file://", "s3://", "minio://"))
        ):
            raise DataControlError("OBJECT_PATH_INVALID")
        if any(ord(ch) < 32 or ch == "\x7f" for ch in name) or "\n" in name or "\r" in name:
            raise DataControlError("OBJECT_PATH_INVALID")
        if len(name) > 180:
            stem, dot, suffix = name.rpartition(".")
            name = f"{stem[:120]}{dot}{suffix[:32]}" if dot else name[:180]
        return quote(name, safe="._-")

    def object_key(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_name: str,
        logical_object_id: str,
        safe_filename: str,
        prefix_template: str,
    ) -> str:
        now = datetime.now(UTC)
        parts = {
            "tenant_id": self._segment(tenant_id, "tenant_id"),
            "biz_domain": self._segment(biz_domain, "biz_domain"),
            "resource_name": self._segment(resource_name, "resource_name"),
            "logical_object_id": self._segment(logical_object_id, "logical_object_id"),
            "yyyy": f"{now.year:04d}",
            "mm": f"{now.month:02d}",
            "safe_filename": safe_filename,
        }
        raw = prefix_template.format(**parts)
        normalized = posixpath.normpath(raw)
        expected_prefix = (
            f"tenant/{parts['tenant_id']}/{parts['biz_domain']}/{parts['resource_name']}/"
        )
        if (
            normalized.startswith("../")
            or normalized.startswith("/")
            or not normalized.startswith(expected_prefix)
        ):
            raise DataControlError("OBJECT_PATH_INVALID")
        return normalized

    @staticmethod
    def digest(object_key: str) -> str:
        return hashlib.sha256(object_key.encode()).hexdigest()

    def _segment(self, value: str, field: str) -> str:
        if not value or any(ord(ch) < 32 or ch in {"/", "\\", ":"} for ch in value):
            raise DataControlError("OBJECT_PATH_INVALID", f"{field} is invalid")
        if not self._safe_segment.match(value):
            raise DataControlError("OBJECT_PATH_INVALID", f"{field} is invalid")
        return quote(value, safe="._-")
