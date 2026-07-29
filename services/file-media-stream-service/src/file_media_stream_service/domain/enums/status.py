from enum import StrEnum


class FileResourceStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADING = "UPLOADING"
    AVAILABLE = "AVAILABLE"
    PROCESSING = "PROCESSING"
    QUARANTINED = "QUARANTINED"
    DELETING = "DELETING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class StreamSessionStatus(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ProcessingJobStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class GrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
