from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from data_control_service.contracts.errors import ERROR_CATALOG
from data_control_service.contracts.response import DataResponse, ErrorBody
from data_control_service.domain.exceptions import DataControlError


def _error_response(
    *,
    request_id: str,
    trace_id: str,
    code: str,
    message: str | None = None,
    details: list[dict[str, object]] | None = None,
    incident_id: str | None = None,
) -> JSONResponse:
    spec = ERROR_CATALOG[code]
    body = DataResponse(
        request_id=request_id,
        trace_id=trace_id,
        success=False,
        code=code,
        message=message or spec.message,
        error=ErrorBody(
            category=spec.category.value,
            retryable=spec.retryable,
            details=details or [],
            incident_id=incident_id,
        ),
        meta={},
    )
    return JSONResponse(
        status_code=spec.http_status, content=body.model_dump(mode="json", exclude_none=True)
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DataControlError)
    async def data_control_error_handler(request: Request, exc: DataControlError) -> JSONResponse:
        return _error_response(
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            code=exc.code,
            message=exc.message,
            details=exc.details,
            incident_id=exc.incident_id,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"loc": ".".join(map(str, item["loc"])), "msg": item["msg"]} for item in exc.errors()
        ]
        code = (
            "IDEMPOTENCY_KEY_REQUIRED"
            if any("idempotency_key" in item["msg"] for item in exc.errors())
            else "REQUEST_SCHEMA_INVALID"
        )
        return _error_response(
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            code=code,
            details=details,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            code="INTERNAL_ERROR",
            incident_id=f"inc_{uuid4().hex}",
        )


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or "req_unavailable"


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id") or f"trace_{uuid4().hex}"
