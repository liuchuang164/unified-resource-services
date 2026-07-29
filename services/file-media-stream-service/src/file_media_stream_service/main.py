from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from file_media_stream_service.application.dto import (
    ToolExecuteRequest,
    ToolResponse,
    UnifiedRequest,
    UnifiedResponse,
)
from file_media_stream_service.bootstrap import Container, build_container
from file_media_stream_service.config import Settings
from file_media_stream_service.gateway.registry import ToolNotExecutable
from file_media_stream_service.observability import configure_logging


def create_app(container: Container | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)
    app = FastAPI(title="文件/音视频流式服务", version="0.1.0")
    app.state.container = container

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = await request.json()
        context = body.get("context", {}) if isinstance(body, dict) else {}
        return JSONResponse(
            status_code=422,
            content={
                "request_id": context.get("request_id", "unknown"),
                "trace_id": context.get("trace_id", "unknown"),
                "success": False,
                "data": None,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed",
                    "retryable": False,
                    "details": {"errors": len(exc.errors())},
                },
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/api/v1/operations/execute", response_model=UnifiedResponse)
    async def execute_operation(request: UnifiedRequest) -> UnifiedResponse:
        return await container.entry.execute(request)

    @app.get("/api/v1/tools")
    async def list_tools() -> dict[str, list[dict[str, Any]]]:
        return {"tools": container.gateway.list_tools()}

    @app.get("/api/v1/tools/{tool_name}/schema")
    async def get_tool_schema(tool_name: str) -> dict[str, Any]:
        schema = container.gateway.get_schema(tool_name)
        if schema is None:
            raise HTTPException(status_code=404, detail="Tool not found")
        return {"tool_name": tool_name, "schema": schema}

    @app.post("/api/v1/tools/execute", response_model=ToolResponse)
    async def execute_tool(request: ToolExecuteRequest) -> ToolResponse:
        try:
            return await container.gateway.execute(request)
        except ToolNotExecutable as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return app


app = create_app()
