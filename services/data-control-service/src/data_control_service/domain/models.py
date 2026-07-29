from dataclasses import dataclass
from typing import Any

from data_control_service.contracts.enums import DataTarget, Operation, TransactionMode


@dataclass(frozen=True)
class ExecutionContext:
    tenant_id: str
    biz_domain: str
    subject_id: str
    subject_type: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    source: str
    request_id: str
    trace_id: str


@dataclass(frozen=True)
class RouteDecision:
    route_id: str
    adapter_name: str
    target: DataTarget
    logical_resource: str
    read_write_mode: str
    timeout_ms: int
    transaction_mode: TransactionMode
    policy_version: str


@dataclass(frozen=True)
class AdapterCommand:
    operation: Operation
    logical_resource: str
    validated_payload: dict[str, Any]
    scope: tuple[str, str]
    timeout_ms: int
    route_id: str
    expected_version: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    status: str
    data: Any | None = None
    affected_count: int = 0
    resource_version: str | None = None
    cursor: str | None = None
    has_more: bool = False
    adapter_metadata: dict[str, Any] | None = None
