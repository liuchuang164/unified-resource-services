from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    CONTRACT = "CONTRACT"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    IDEMPOTENCY = "IDEMPOTENCY"
    ROUTING = "ROUTING"
    ADAPTER = "ADAPTER"
    DATA = "DATA"
    TRANSACTION = "TRANSACTION"
    AUDIT = "AUDIT"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class ErrorSpec:
    http_status: int
    retryable: bool
    category: ErrorCategory
    message: str


ERROR_CATALOG: dict[str, ErrorSpec] = {
    "CONTRACT_VERSION_UNSUPPORTED": ErrorSpec(
        400, False, ErrorCategory.CONTRACT, "contract version is unsupported"
    ),
    "REQUEST_SCHEMA_INVALID": ErrorSpec(
        400, False, ErrorCategory.CONTRACT, "request schema is invalid"
    ),
    "OPERATION_NOT_SUPPORTED": ErrorSpec(
        422, False, ErrorCategory.CONTRACT, "operation is not supported"
    ),
    "RESOURCE_TYPE_UNKNOWN": ErrorSpec(
        422, False, ErrorCategory.CONTRACT, "resource type is unknown"
    ),
    "PAYLOAD_TOO_LARGE": ErrorSpec(413, False, ErrorCategory.CONTRACT, "payload is too large"),
    "AUTH_REQUIRED": ErrorSpec(
        401, False, ErrorCategory.AUTHENTICATION, "authentication is required"
    ),
    "AUTH_TOKEN_INVALID": ErrorSpec(
        401, False, ErrorCategory.AUTHENTICATION, "authentication credential is invalid"
    ),
    "AUTH_SCOPE_MISMATCH": ErrorSpec(
        403, False, ErrorCategory.AUTHORIZATION, "request scope is not permitted"
    ),
    "PERMISSION_DENIED": ErrorSpec(403, False, ErrorCategory.AUTHORIZATION, "permission denied"),
    "POLICY_DENIED": ErrorSpec(403, False, ErrorCategory.AUTHORIZATION, "policy denied"),
    "FIELD_ACCESS_DENIED": ErrorSpec(
        403, False, ErrorCategory.AUTHORIZATION, "field access denied"
    ),
    "IDEMPOTENCY_KEY_REQUIRED": ErrorSpec(
        400, False, ErrorCategory.IDEMPOTENCY, "idempotency key is required"
    ),
    "IDEMPOTENCY_IN_PROGRESS": ErrorSpec(
        409, True, ErrorCategory.IDEMPOTENCY, "idempotent request is still processing"
    ),
    "IDEMPOTENCY_KEY_CONFLICT": ErrorSpec(
        409, False, ErrorCategory.IDEMPOTENCY, "idempotency key conflicts with a different request"
    ),
    "IDEMPOTENCY_RECOVERY_REQUIRED": ErrorSpec(
        409,
        False,
        ErrorCategory.IDEMPOTENCY,
        "idempotent request completed business write and requires control-plane recovery",
    ),
    "ROUTE_NOT_FOUND": ErrorSpec(422, False, ErrorCategory.ROUTING, "route was not found"),
    "ADAPTER_NOT_REGISTERED": ErrorSpec(
        500, False, ErrorCategory.ADAPTER, "adapter is not registered"
    ),
    "ADAPTER_UNAVAILABLE": ErrorSpec(503, True, ErrorCategory.ADAPTER, "adapter is unavailable"),
    "ADAPTER_TIMEOUT": ErrorSpec(504, True, ErrorCategory.ADAPTER, "adapter timed out"),
    "ADAPTER_RESPONSE_INVALID": ErrorSpec(
        502, True, ErrorCategory.ADAPTER, "adapter response is invalid"
    ),
    "RESOURCE_NOT_FOUND": ErrorSpec(404, False, ErrorCategory.DATA, "resource was not found"),
    "DATA_CONSTRAINT_VIOLATION": ErrorSpec(
        422, False, ErrorCategory.DATA, "data constraint violation"
    ),
    "LOCK_CONFLICT": ErrorSpec(409, True, ErrorCategory.DATA, "resource lock conflict"),
    "RESOURCE_VERSION_CONFLICT": ErrorSpec(
        409, True, ErrorCategory.DATA, "resource version conflict"
    ),
    "TRANSACTION_NOT_SUPPORTED": ErrorSpec(
        422, False, ErrorCategory.TRANSACTION, "transaction is not supported"
    ),
    "TRANSACTION_ROLLED_BACK": ErrorSpec(
        409, True, ErrorCategory.TRANSACTION, "transaction rolled back"
    ),
    "TRANSACTION_DEADLOCK": ErrorSpec(
        409, True, ErrorCategory.TRANSACTION, "transaction deadlock detected"
    ),
    "TRANSACTION_SERIALIZATION_FAILURE": ErrorSpec(
        409, True, ErrorCategory.TRANSACTION, "transaction serialization failure"
    ),
    "PARTIAL_FAILURE": ErrorSpec(502, True, ErrorCategory.TRANSACTION, "batch partially failed"),
    "AUDIT_WRITE_FAILED": ErrorSpec(503, True, ErrorCategory.AUDIT, "audit write failed"),
    "CONFIGURATION_INVALID": ErrorSpec(
        500, False, ErrorCategory.INTERNAL, "configuration is invalid"
    ),
    "INTERNAL_ERROR": ErrorSpec(500, True, ErrorCategory.INTERNAL, "internal error"),
}
