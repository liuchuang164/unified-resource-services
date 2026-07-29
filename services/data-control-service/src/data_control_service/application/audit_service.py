import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from data_control_service.contracts.request import DataRequest
from data_control_service.domain.models import ExecutionContext, RouteDecision

SENSITIVE_KEYS = {"authorization", "cookie", "token", "password", "secret", "connection_string"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def stable_digest(value: Any) -> str:
    return hashlib.sha256(repr(redact(value)).encode()).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    occurred_at: str
    tenant_id: str
    biz_domain: str
    subject_id: str
    source: str
    request_id: str
    trace_id: str
    operation: str
    resource: str
    adapter: str | None
    status: str
    code: str
    route_id: str | None
    idempotency_key_digest: str | None
    payload_digest: str


class InMemoryAuditService:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    async def record(
        self,
        request: DataRequest,
        context: ExecutionContext,
        *,
        status: str,
        code: str,
        route: RouteDecision | None = None,
    ) -> None:
        idem_digest = stable_digest(request.idempotency_key) if request.idempotency_key else None
        self.records.append(
            AuditRecord(
                occurred_at=datetime.now(UTC).isoformat(),
                tenant_id=context.tenant_id,
                biz_domain=context.biz_domain,
                subject_id=context.subject_id,
                source=context.source,
                request_id=context.request_id,
                trace_id=context.trace_id,
                operation=request.operation.value,
                resource=f"{request.resource.type}:{request.resource.name}",
                adapter=route.adapter_name if route else None,
                status=status,
                code=code,
                route_id=route.route_id if route else None,
                idempotency_key_digest=idem_digest,
                payload_digest=stable_digest(request.payload.model_dump(mode="json")),
            )
        )
