from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ObjectStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    AVAILABLE = "AVAILABLE"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class UploadMode(StrEnum):
    PROXY = "PROXY"
    PRESIGNED = "PRESIGNED"


@dataclass(frozen=True)
class ObjectRecord:
    id: str
    logical_object_id: str
    tenant_id: str
    biz_domain: str
    resource_type: str
    resource_name: str
    bucket_reference: str
    object_key: str
    object_key_digest: str
    safe_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None
    etag: str | None
    status: ObjectStatus
    upload_mode: UploadMode
    created_by: str
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    deleted_at: datetime | None
