from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from external_access_service.bootstrap import Container, build_container
from external_access_service.domain.errors import DomainError, ErrorCode, OperationNotFound
from external_access_service.domain.models import (
    DispatchStatus,
    ErrorDetail,
    ExternalDispatchRequest,
    ExternalDispatchResponse,
    ProviderCode,
)
from external_access_service.infrastructure.config import Settings
from external_access_service.infrastructure.observability.logging import configure_logging
from external_access_service.interfaces.eag.gateway import ToolExecuteRequest, ToolResponse


def create_app(container: Container | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)
    app = FastAPI(title="External Access Service", version="0.1.0")
    app.state.container = container

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed",
                    "retryable": False,
                    "details": {"errors": len(exc.errors())},
                }
            },
        )

    @app.exception_handler(DomainError)
    async def domain_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code),
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "details": exc.details,
                }
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        provider_health = await container.provider_health.check_all()
        return {
            "status": "ready",
            "config": "ok",
            "providers": _ready_provider_status(provider_health),
        }

    @app.get("/external/operations")
    async def list_operations(
        request: Request,
        tenant_id: str = Query(min_length=1),
        biz_domain: str = Query(min_length=1),
    ) -> dict[str, list[dict[str, Any]]]:
        trusted = container.context_resolver.resolve_query(
            request.headers,
            {"tenant_id": tenant_id, "biz_domain": biz_domain},
        )
        return {
            "operations": [
                item.model_dump(mode="json")
                for item in container.operations.list(trusted.tenant_id, trusted.biz_domain)
            ]
        }

    @app.get("/external/operations/{operation}/schema")
    async def operation_schema(operation: str) -> dict[str, Any]:
        try:
            item = container.operations.get(operation)
        except OperationNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        return {"operation": item.operation, "schema": item.payload_schema}

    @app.post("/external/dispatch", response_model=ExternalDispatchResponse)
    async def dispatch(
        http_request: Request, request: ExternalDispatchRequest
    ) -> ExternalDispatchResponse:
        try:
            trusted_request = container.context_resolver.resolve_dispatch(
                http_request.headers, request
            )
        except DomainError as exc:
            return _failure_response(request, exc)
        return await container.entry.dispatch(trusted_request)

    @app.get("/external/usage")
    async def usage(
        request: Request,
        tenant_id: str = Query(min_length=1),
        biz_domain: str = Query(min_length=1),
        operation: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        trusted = container.context_resolver.resolve_query(
            request.headers,
            {"tenant_id": tenant_id, "biz_domain": biz_domain},
        )
        return {
            "tenant_id": trusted.tenant_id,
            "biz_domain": trusted.biz_domain,
            "usage": await container.usage_meter.query_usage(
                tenant_id=trusted.tenant_id,
                biz_domain=trusted.biz_domain,
                operation=operation,
                provider=provider,
            ),
        }

    @app.get("/external/audit")
    async def audit(
        request: Request,
        tenant_id: str = Query(min_length=1),
        biz_domain: str = Query(min_length=1),
        request_id: str | None = None,
        operation: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        trusted = container.context_resolver.resolve_query(
            request.headers,
            {"tenant_id": tenant_id, "biz_domain": biz_domain},
        )
        if request_id:
            records = await container.audit.query_by_request_id(
                tenant_id=trusted.tenant_id,
                biz_domain=trusted.biz_domain,
                request_id=request_id,
            )
        else:
            records = await container.audit.query_by_tenant(
                tenant_id=trusted.tenant_id,
                biz_domain=trusted.biz_domain,
                operation=operation,
                status=status,
            )
        return {"tenant_id": trusted.tenant_id, "biz_domain": trusted.biz_domain, "audit": records}

    @app.get("/external/providers")
    async def providers() -> dict[str, list[dict[str, Any]]]:
        return {
            "providers": [
                provider.model_dump(mode="json")
                for provider in container.provider_registry.list_providers()
            ]
        }

    @app.get("/external/providers/health")
    async def providers_health() -> dict[str, dict[str, object]]:
        return await container.provider_health.check_all()

    @app.get("/external/providers/{provider}/health")
    async def provider_health(provider: str) -> dict[str, object]:
        return await container.provider_health.check(ProviderCode(provider))

    @app.get("/external/providers/{provider}/operations")
    async def provider_operations(provider: str) -> dict[str, Any]:
        typed = container.provider_registry.get(ProviderCode(provider))
        return {
            "provider": typed.provider_code.value,
            "operations": list(typed.supported_operations),
            "status": typed.status.value,
        }

    @app.get("/eag/tools")
    async def list_tools(
        request: Request,
        tenant_id: str = Query(min_length=1),
        biz_domain: str = Query(min_length=1),
    ) -> dict[str, list[dict[str, Any]]]:
        trusted = container.context_resolver.resolve_query(
            request.headers,
            {"tenant_id": tenant_id, "biz_domain": biz_domain},
            default_source="AGENT_TOOL",
        )
        return {"tools": container.gateway.list_tools(trusted.tenant_id, trusted.biz_domain)}

    @app.get("/eag/tools/{tool_name}/schema")
    async def tool_schema(tool_name: str) -> dict[str, Any]:
        try:
            return container.gateway.schema(tool_name)
        except DomainError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc

    @app.post("/eag/tools/execute", response_model=ToolResponse)
    async def execute_tool(http_request: Request, request: ToolExecuteRequest) -> ToolResponse:
        trusted_request = container.context_resolver.resolve_tool(http_request.headers, request)
        return await container.gateway.execute(trusted_request)

    return app


def _failure_response(
    request: ExternalDispatchRequest, error: DomainError
) -> ExternalDispatchResponse:
    return ExternalDispatchResponse(
        request_id=request.request_id,
        trace_id=request.trace_id,
        tenant_id=request.auth_context.tenant_id,
        biz_domain=request.biz_context.biz_domain,
        operation=request.operation,
        provider=request.provider.provider_code,
        status=DispatchStatus.FAILED,
        data=None,
        latency_ms=0,
        error=ErrorDetail(
            code=error.code.value if isinstance(error.code, ErrorCode) else str(error.code),
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        ),
    )


def _ready_provider_status(
    provider_health: dict[str, dict[str, object]],
) -> dict[str, object]:
    statuses: dict[str, object] = {}
    for provider, health in provider_health.items():
        details = health.get("details")
        if isinstance(details, dict):
            statuses[provider] = details.get("status", health["status"])
        else:
            statuses[provider] = health["status"]
    return statuses


app = create_app()
