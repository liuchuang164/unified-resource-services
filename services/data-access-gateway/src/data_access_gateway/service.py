from time import perf_counter
from typing import Any

from pydantic import ValidationError

from data_access_gateway.auth import CapabilityPrincipal
from data_access_gateway.client import DataControlClient
from data_access_gateway.contracts import ToolError, ToolExecuteRequest, ToolResponse
from data_access_gateway.errors import GatewayError
from data_access_gateway.minio_tool import to_data_request
from data_access_gateway.registry import ToolRegistry


class ToolExecutionService:
    def __init__(self, registry: ToolRegistry, client: DataControlClient) -> None:
        self._registry = registry
        self._client = client

    async def execute(
        self,
        request: ToolExecuteRequest,
        principal: CapabilityPrincipal,
        capability_token: str,
    ) -> tuple[int, ToolResponse]:
        started = perf_counter()
        self._validate_scope(request, principal)
        definition, action = self._registry.action(request.tool_name, request.action)
        principal.authorize(definition.name, action.name)
        try:
            params = action.params_model.model_validate(request.params)
        except ValidationError as exc:
            raise GatewayError(
                "TOOL_PARAMS_INVALID",
                details=[
                    {"loc": ".".join(map(str, item["loc"])), "msg": item["msg"]}
                    for item in exc.errors()
                ],
            ) from exc
        data_request = to_data_request(request, principal, action, params)
        downstream = await self._client.dispatch(data_request, capability_token)
        duration_ms = round((perf_counter() - started) * 1000)
        if downstream.body["success"] is True:
            return downstream.status_code, ToolResponse(
                request_id=request.request_id,
                trace_id=str(downstream.body.get("trace_id") or request.trace_id),
                success=True,
                tool_name=request.tool_name,
                action=request.action,
                data=downstream.body.get("data"),
                meta={
                    "duration_ms": duration_ms,
                    "idempotency_replayed": bool(
                        downstream.body.get("meta", {}).get("idempotency_replayed", False)
                    ),
                },
            )
        error_body = downstream.body.get("error") or {}
        return downstream.status_code, ToolResponse(
            request_id=request.request_id,
            trace_id=str(downstream.body.get("trace_id") or request.trace_id),
            success=False,
            tool_name=request.tool_name,
            action=request.action,
            error=ToolError(
                code=str(downstream.body.get("code") or "TOOL_EXECUTION_FAILED"),
                message=str(downstream.body.get("message") or "tool execution failed"),
                retryable=bool(error_body.get("retryable", False)),
                details=_details(error_body.get("details")),
                incident_id=error_body.get("incident_id"),
            ),
            meta={"duration_ms": duration_ms},
        )

    @staticmethod
    def _validate_scope(
        request: ToolExecuteRequest,
        principal: CapabilityPrincipal,
    ) -> None:
        if (
            request.tenant_id != principal.tenant_id
            or request.biz_domain != principal.biz_domain
            or request.session_id != principal.session_id
            or request.task_id != principal.task_id
        ):
            raise GatewayError("TOOL_SCOPE_MISMATCH")


def _details(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
