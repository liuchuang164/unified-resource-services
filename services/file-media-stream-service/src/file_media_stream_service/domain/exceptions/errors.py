from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class InvalidStateTransition(DomainError):
    code = "INVALID_STATE_TRANSITION"


class InvalidObjectName(DomainError):
    code = "INVALID_OBJECT_NAME"


class ResourceNotFound(DomainError):
    code = "RESOURCE_NOT_FOUND"


class FileResourceNotFound(ResourceNotFound):
    code = "FILE_RESOURCE_NOT_FOUND"


class StreamSessionNotFound(ResourceNotFound):
    code = "STREAM_SESSION_NOT_FOUND"


class ProcessingJobNotFound(ResourceNotFound):
    code = "PROCESSING_JOB_NOT_FOUND"


class IdempotencyConflict(DomainError):
    code = "IDEMPOTENCY_CONFLICT"


class SecurityError(DomainError):
    code = "PERMISSION_DENIED"


class Unauthenticated(SecurityError):
    code = "UNAUTHENTICATED"


class PermissionDenied(SecurityError):
    code = "PERMISSION_DENIED"


class QuotaExceeded(SecurityError):
    code = "QUOTA_EXCEEDED"


class ReplayDetected(SecurityError):
    code = "REPLAY_DETECTED"
