from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from data_access_gateway.auth import CapabilityPrincipal, CapabilityTokenVerifier
from data_access_gateway.contracts import ToolError, ToolExecuteRequest, ToolResponse
from data_access_gateway.dependencies import (
    close_dependencies,
    get_data_control_client,
    get_registry,
    get_tool_execution_service,
    get_verifier,
)
from data_access_gateway.errors import GatewayError
from data_access_gateway.registry import ToolDefinition, ToolRegistry
from data_access_gateway.service import ToolExecutionService

logger = structlog.get_logger()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await close_dependencies()

    app = FastAPI(title="data-access-gateway", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
        logger.warning(
            "gateway_request_rejected",
            request_id=request.headers.get("x-request-id"),
            trace_id=request.headers.get("x-trace-id"),
            path=request.url.path,
            error_code=exc.code,
        )
        body = _error_response(
            request=request,
            code=exc.code,
            message=exc.spec.message,
            retryable=exc.spec.retryable,
            details=exc.details,
        )
        return JSONResponse(status_code=exc.spec.http_status, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_error_response(
                request=request,
                code="TOOL_PARAMS_INVALID",
                message="tool request is invalid",
                retryable=False,
                details=[
                    {"loc": ".".join(map(str, item["loc"])), "msg": item["msg"]}
                    for item in exc.errors()
                ],
            ),
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        is_ready = await get_data_control_client().ready()
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "status": "READY" if is_ready else "NOT_READY",
                "ready": is_ready,
                "components": {
                    "tool_registry": {"status": "ok"},
                    "data_control_service": {"status": "ok" if is_ready else "error"},
                },
            },
        )

    @app.get("/dag/tools")
    async def list_tools(
        verifier: Annotated[CapabilityTokenVerifier, Depends(get_verifier)],
        registry: Annotated[ToolRegistry, Depends(get_registry)],
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _, principal = verifier.verify_authorization(authorization)
        return {
            "contract_version": "1.0",
            "tools": [
                _tool_summary(definition, principal)
                for definition in registry.list_visible(principal.allowed_tools)
            ],
        }

    @app.get("/dag/tools/{tool_name}/schema")
    async def tool_schema(
        tool_name: str,
        verifier: Annotated[CapabilityTokenVerifier, Depends(get_verifier)],
        registry: Annotated[ToolRegistry, Depends(get_registry)],
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _, principal = verifier.verify_authorization(authorization)
        definition = registry.get(tool_name)
        if tool_name not in principal.allowed_tools:
            raise GatewayError("CAPABILITY_SCOPE_DENIED")
        actions = []
        for action in definition.actions:
            if f"{tool_name}:{action.name}" in principal.allowed_actions:
                actions.append(
                    {
                        "name": action.name,
                        "operation": action.operation,
                        "write": action.write,
                        "high_risk": action.high_risk,
                        "params_schema": action.params_model.model_json_schema(),
                    }
                )
        return {
            "contract_version": "1.0",
            "tool_name": definition.name,
            "tool_version": definition.version,
            "actions": actions,
        }

    @app.post("/dag/tools/execute")
    async def execute_tool(
        tool_request: ToolExecuteRequest,
        verifier: Annotated[CapabilityTokenVerifier, Depends(get_verifier)],
        service: Annotated[ToolExecutionService, Depends(get_tool_execution_service)],
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        token, principal = verifier.verify_authorization(authorization)
        status_code, response = await service.execute(tool_request, principal, token)
        logger.info(
            "tool_execute_completed",
            request_id=response.request_id,
            trace_id=response.trace_id,
            tenant_id=principal.tenant_id,
            biz_domain=principal.biz_domain,
            agent_id=principal.agent_id,
            tool_name=response.tool_name,
            action=response.action,
            success=response.success,
            error_code=response.error.code if response.error else None,
            duration_ms=response.meta.get("duration_ms"),
        )
        return JSONResponse(
            status_code=status_code,
            content=response.model_dump(mode="json", exclude_none=True),
        )

    return app


def _tool_summary(
    definition: ToolDefinition,
    principal: CapabilityPrincipal,
) -> dict[str, object]:
    name = definition.name
    return {
        "name": name,
        "version": definition.version,
        "description": definition.description,
        "actions": [
            action.name
            for action in definition.actions
            if f"{name}:{action.name}" in principal.allowed_actions
        ],
    }


def _error_response(
    *,
    request: Request,
    code: str,
    message: str,
    retryable: bool,
    details: list[dict[str, object]],
) -> dict[str, object]:
    return ToolResponse(
        request_id=request.headers.get("x-request-id") or "req_unavailable",
        trace_id=request.headers.get("x-trace-id") or f"trace_{uuid4().hex}",
        success=False,
        tool_name="unavailable",
        action="unavailable",
        error=ToolError(
            code=code,
            message=message,
            retryable=retryable,
            details=details,
        ),
    ).model_dump(mode="json", exclude_none=True)


app = create_app()
