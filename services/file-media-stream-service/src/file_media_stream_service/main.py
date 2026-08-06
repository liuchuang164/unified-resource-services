import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response, StreamingResponse

from file_media_stream_service.application.dto import (
    ToolExecuteRequest,
    ToolResponse,
    UnifiedRequest,
    UnifiedResponse,
)
from file_media_stream_service.application.use_cases.service import UploadPartTransferFailed
from file_media_stream_service.bootstrap import Container, ProductionContainer, build_container
from file_media_stream_service.config import Settings
from file_media_stream_service.domain.exceptions import FileResourceNotFound
from file_media_stream_service.gateway.registry import ToolNotExecutable
from file_media_stream_service.observability import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    container: Container | ProductionContainer | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)
    app = FastAPI(title="文件/音视频流式服务", version="0.1.0")
    app.state.container = container

    @app.middleware("http")
    async def transaction_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not isinstance(container, ProductionContainer):
            return await call_next(request)
        if container.provisioning_compensator is not None:
            container.provisioning_compensator.begin()
        if container.file_metadata_commit_tracker is not None:
            container.file_metadata_commit_tracker.begin()
        try:
            response = await call_next(request)
            await container.transaction.commit()
            if container.provisioning_compensator is not None:
                container.provisioning_compensator.clear()
            if container.file_metadata_commit_tracker is not None:
                container.file_metadata_commit_tracker.clear()
            return response
        except Exception:
            await container.transaction.rollback()
            await container.transaction.close()
            if container.provisioning_compensator is not None:
                try:
                    await container.provisioning_compensator.compensate()
                except Exception:
                    logger.exception("stream provisioning compensation failed")
            if container.file_metadata_commit_tracker is not None:
                try:
                    await container.file_metadata_commit_tracker.reconcile()
                except Exception:
                    logger.exception("file metadata reconciliation recording failed")
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "error": "transaction_failed"},
            )
        finally:
            await container.transaction.close()

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

    @app.get("/ready", response_model=None)
    async def ready() -> dict[str, Any] | JSONResponse:
        if isinstance(container, ProductionContainer):
            dependencies = await container.readiness.check()
            ready_status = all(value == "ok" for value in dependencies.values())
            payload: dict[str, Any] = {
                "status": "ready" if ready_status else "unavailable",
                "dependencies": dependencies,
            }
            if not ready_status:
                return JSONResponse(status_code=503, content=payload)
            return payload
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

    @app.get("/api/v1/files/range", response_model=None)
    async def stream_file_range(
        reference_id: str = Header(alias="X-Range-Access-Reference"),
    ) -> StreamingResponse:
        try:
            grant, resource, stream = await container.entry.consume_range_reference(reference_id)
        except Exception as error:
            raise HTTPException(status_code=403, detail="Range access denied") from error
        end = grant.offset + grant.length - 1
        return StreamingResponse(
            stream,
            status_code=206,
            media_type=resource.mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(grant.length),
                "Content-Range": f"bytes {grant.offset}-{end}/{resource.size_bytes}",
                "Cache-Control": "no-store",
            },
        )

    @app.put("/api/v1/files/upload-part", response_model=None)
    async def upload_file_part(
        request: Request,
        reference_id: str = Header(alias="X-Upload-Part-Reference"),
        content_length: int = Header(alias="Content-Length"),
    ) -> Response:
        if content_length <= 0:
            raise HTTPException(status_code=400, detail="Upload part is empty")
        if content_length > settings.max_upload_part_bytes:
            raise HTTPException(status_code=413, detail="Upload part is too large")

        async def bounded_stream() -> AsyncIterator[bytes]:
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > content_length:
                    raise ValueError("Upload part exceeds declared content length")
                yield chunk
            if received != content_length:
                raise ValueError("Upload part does not match declared content length")

        try:
            grant, etag = await container.entry.consume_upload_part_reference(
                reference_id, bounded_stream(), content_length
            )
        except FileResourceNotFound as error:
            await container.entry.audit_upload_part_denied()
            raise HTTPException(status_code=403, detail="Upload part access denied") from error
        except UploadPartTransferFailed as error:
            if isinstance(error.__cause__, ValueError):
                raise HTTPException(status_code=400, detail="Upload part is invalid") from error
            raise HTTPException(
                status_code=503, detail="Upload part service unavailable"
            ) from error
        return Response(
            status_code=204,
            headers={
                "ETag": etag,
                "X-Part-Number": str(grant.part_number),
                "Cache-Control": "no-store",
            },
        )

    return app


app = create_app()
