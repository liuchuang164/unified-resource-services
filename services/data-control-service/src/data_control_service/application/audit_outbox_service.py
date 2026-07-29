from data_control_service.application.audit_service import stable_digest
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import WRITE_OPERATIONS
from data_control_service.contracts.errors import ERROR_CATALOG
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.models import AdapterResult, ExecutionContext, RouteDecision
from data_control_service.ports.audit_outbox_repository import (
    AuditEventType,
    AuditOutboxEvent,
    AuditOutboxRepository,
)


class AuditOutboxService:
    def __init__(self, repository: AuditOutboxRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def record_access(
        self,
        request: DataRequest,
        context: ExecutionContext,
        *,
        status: str,
        code: str,
        latency_ms: int,
        route: RouteDecision | None = None,
    ) -> None:
        spec = ERROR_CATALOG.get(code)
        target = route.target.value if route else request.resource.target.value
        payload: dict[str, object] = {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "tenant_id": context.tenant_id,
            "biz_domain": context.biz_domain,
            "actor_id": context.subject_id,
            "actor_type": context.subject_type,
            "source": context.source,
            "operation": request.operation.value,
            "target": target,
            "logical_resource_type": request.resource.type,
            "logical_resource_name": request.resource.name,
            "resource_id": request.resource.resource_id,
            "policy_decision": "ALLOW" if status in {"SUCCEEDED", "REPLAYED"} else "DENY",
            "policy_id": None,
            "result_status": status,
            "http_status": spec.http_status if spec else 200,
            "error_code": None if code == "OK" else code,
            "retryable": spec.retryable if spec else False,
            "latency_ms": latency_ms,
            "metadata_digest": stable_digest(request.metadata),
        }
        await self._enqueue(AuditEventType.ACCESS, request, context, route, status, code, payload)

    async def record_change(
        self,
        request: DataRequest,
        context: ExecutionContext,
        result: AdapterResult,
        *,
        status: str,
        code: str,
        route: RouteDecision,
    ) -> None:
        if request.operation not in WRITE_OPERATIONS or status != "SUCCEEDED":
            return
        changed_fields = (
            sorted(request.payload.data) if isinstance(request.payload.data, dict) else []
        )
        payload: dict[str, object] = {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "tenant_id": context.tenant_id,
            "biz_domain": context.biz_domain,
            "actor_id": context.subject_id,
            "target": route.target.value,
            "logical_resource_type": request.resource.type,
            "logical_resource_name": request.resource.name,
            "resource_id": request.resource.resource_id
            or str((result.data or {}).get("resource_id", "")),
            "operation": request.operation.value,
            "before_digest": None,
            "after_digest": stable_digest(result.data),
            "changed_fields": {"fields": changed_fields},
            "result_status": status,
            "error_code": None if code == "OK" else code,
        }
        await self._enqueue(AuditEventType.CHANGE, request, context, route, status, code, payload)

    async def _enqueue(
        self,
        event_type: AuditEventType,
        request: DataRequest,
        context: ExecutionContext,
        route: RouteDecision | None,
        status: str,
        code: str,
        payload: dict[str, object],
    ) -> None:
        target = route.target.value if route else request.resource.target.value
        resource_id = request.resource.resource_id or str(payload.get("resource_id") or "")
        event_id = stable_digest(
            {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "event_type": event_type.value,
                "status": status,
                "code": code,
                "resource_id": resource_id,
            }
        )
        await self._repository.enqueue(
            AuditOutboxEvent(
                event_id=event_id,
                tenant_id=context.tenant_id,
                biz_domain=context.biz_domain,
                request_id=context.request_id,
                trace_id=context.trace_id,
                actor_id=context.subject_id,
                event_type=event_type,
                target=target,
                logical_resource_type=request.resource.type,
                logical_resource_name=request.resource.name,
                resource_id=resource_id or None,
                operation=request.operation.value,
                audit_payload=payload,
                payload_digest=stable_digest(payload),
                max_attempts=self._settings.audit_outbox_max_attempts,
            )
        )
