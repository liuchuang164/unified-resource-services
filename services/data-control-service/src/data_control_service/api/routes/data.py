from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse

from data_control_service.api.dependencies import get_auth_provider, get_data_control_service
from data_control_service.application.data_control_service import DataControlService
from data_control_service.contracts.request import DataRequest
from data_control_service.ports.auth_provider import (
    AuthenticationCredential,
    AuthProvider,
    RequestContext,
)

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/dispatch")
async def dispatch(
    request: DataRequest,
    http_request: FastAPIRequest,
    service: Annotated[DataControlService, Depends(get_data_control_service)],
    auth_provider: Annotated[AuthProvider, Depends(get_auth_provider)],
    x_request_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
) -> JSONResponse:
    if x_request_id and request.request_id != x_request_id:
        from data_control_service.domain.exceptions import DataControlError

        raise DataControlError("REQUEST_SCHEMA_INVALID", "x-request-id must match request_id")
    if x_trace_id and request.trace_id and request.trace_id != x_trace_id:
        from data_control_service.domain.exceptions import DataControlError

        raise DataControlError("REQUEST_SCHEMA_INVALID", "x-trace-id must match trace_id")
    request_context = RequestContext(
        request_id=request.request_id,
        trace_id=request.trace_id or x_trace_id,
        source=request.source.value,
        client_host=http_request.client.host if http_request.client else None,
    )
    credential = AuthenticationCredential(headers=dict(http_request.headers))
    principal = await auth_provider.authenticate(credential, request_context)
    response = await service.dispatch(request, principal, request_context)
    return JSONResponse(
        status_code=status.HTTP_200_OK, content=response.model_dump(mode="json", exclude_none=True)
    )
