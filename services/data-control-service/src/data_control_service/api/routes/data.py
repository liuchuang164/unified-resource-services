from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from data_control_service.api.dependencies import get_data_control_service
from data_control_service.application.data_control_service import DataControlService
from data_control_service.contracts.request import DataRequest

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/dispatch")
async def dispatch(
    request: DataRequest,
    service: Annotated[DataControlService, Depends(get_data_control_service)],
    x_request_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
) -> JSONResponse:
    if x_request_id and request.request_id != x_request_id:
        from data_control_service.domain.exceptions import DataControlError

        raise DataControlError("REQUEST_SCHEMA_INVALID", "x-request-id must match request_id")
    if x_trace_id and request.trace_id and request.trace_id != x_trace_id:
        from data_control_service.domain.exceptions import DataControlError

        raise DataControlError("REQUEST_SCHEMA_INVALID", "x-trace-id must match trace_id")
    response = await service.dispatch(request)
    return JSONResponse(
        status_code=status.HTTP_200_OK, content=response.model_dump(mode="json", exclude_none=True)
    )
