from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from external_access_service.bootstrap import Container, build_container
from external_access_service.domain.errors import DomainError, OperationNotFound
from external_access_service.domain.models import ExternalDispatchRequest, ExternalDispatchResponse
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        provider_health = await container.provider.health_check()
        return {
            "status": "ready",
            "config": "ok",
            "providers": {provider_health["provider"]: provider_health["status"]},
        }

    @app.get("/external/operations")
    async def list_operations(
        tenant_id: str = Query(min_length=1), biz_domain: str = Query(min_length=1)
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "operations": [
                item.model_dump(mode="json")
                for item in container.operations.list(tenant_id, biz_domain)
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
    async def dispatch(request: ExternalDispatchRequest) -> ExternalDispatchResponse:
        return await container.entry.dispatch(request)

    @app.get("/eag/tools")
    async def list_tools(
        tenant_id: str = Query(min_length=1), biz_domain: str = Query(min_length=1)
    ) -> dict[str, list[dict[str, Any]]]:
        return {"tools": container.gateway.list_tools(tenant_id, biz_domain)}

    @app.get("/eag/tools/{tool_name}/schema")
    async def tool_schema(tool_name: str) -> dict[str, Any]:
        try:
            return container.gateway.schema(tool_name)
        except DomainError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc

    @app.post("/eag/tools/execute", response_model=ToolResponse)
    async def execute_tool(request: ToolExecuteRequest) -> ToolResponse:
        return await container.gateway.execute(request)

    return app


app = create_app()
