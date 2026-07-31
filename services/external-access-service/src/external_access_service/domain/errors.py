from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_SCOPE_MISMATCH = "TENANT_SCOPE_MISMATCH"
    BIZ_DOMAIN_SCOPE_MISMATCH = "BIZ_DOMAIN_SCOPE_MISMATCH"
    OPERATION_NOT_FOUND = "OPERATION_NOT_FOUND"
    OPERATION_NOT_ALLOWED = "OPERATION_NOT_ALLOWED"
    OPERATION_NOT_AVAILABLE = "OPERATION_NOT_AVAILABLE"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_BAD_RESPONSE = "PROVIDER_BAD_RESPONSE"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DomainError(Exception):
    code = ErrorCode.INTERNAL_ERROR
    retryable = False

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidRequest(DomainError):
    code = ErrorCode.INVALID_REQUEST


class Unauthenticated(DomainError):
    code = ErrorCode.UNAUTHENTICATED


class Forbidden(DomainError):
    code = ErrorCode.FORBIDDEN


class TenantScopeMismatch(DomainError):
    code = ErrorCode.TENANT_SCOPE_MISMATCH


class BizDomainScopeMismatch(DomainError):
    code = ErrorCode.BIZ_DOMAIN_SCOPE_MISMATCH


class OperationNotFound(DomainError):
    code = ErrorCode.OPERATION_NOT_FOUND


class OperationNotAllowed(DomainError):
    code = ErrorCode.OPERATION_NOT_ALLOWED


class OperationNotAvailable(DomainError):
    code = ErrorCode.OPERATION_NOT_AVAILABLE


class ProviderNotFound(DomainError):
    code = ErrorCode.PROVIDER_NOT_FOUND


class ProviderNotConfigured(DomainError):
    code = ErrorCode.PROVIDER_NOT_CONFIGURED


class ProviderAuthFailed(DomainError):
    code = ErrorCode.PROVIDER_AUTH_FAILED


class ProviderRateLimited(DomainError):
    code = ErrorCode.PROVIDER_RATE_LIMITED
    retryable = True


class ProviderTimeout(DomainError):
    code = ErrorCode.PROVIDER_TIMEOUT
    retryable = True


class ProviderUnavailable(DomainError):
    code = ErrorCode.PROVIDER_UNAVAILABLE
    retryable = True


class ProviderBadResponse(DomainError):
    code = ErrorCode.PROVIDER_BAD_RESPONSE


class RateLimitExceeded(DomainError):
    code = ErrorCode.RATE_LIMIT_EXCEEDED
    retryable = True


class CircuitOpen(DomainError):
    code = ErrorCode.CIRCUIT_OPEN
    retryable = True
