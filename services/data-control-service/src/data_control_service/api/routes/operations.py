from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from data_control_service.api.dependencies import get_auth_provider, get_data_control_service
from data_control_service.application.data_control_service import DataControlService
from data_control_service.contracts.enums import Operation
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.ports.auth_provider import (
    AuthenticationCredential,
    AuthProvider,
    RequestContext,
)

router = APIRouter(prefix="/data", tags=["data-discovery"])


async def _authenticate_discovery(
    request: Request,
    auth_provider: AuthProvider,
    biz_domain: str,
) -> None:
    request_id = request.headers.get("x-request-id") or "req_data_operations"
    trace_id = request.headers.get("x-trace-id")
    principal = await auth_provider.authenticate(
        AuthenticationCredential(headers=dict(request.headers)),
        RequestContext(
            request_id=request_id,
            trace_id=trace_id,
            source="DATA_ACCESS_GATEWAY",
            client_host=request.client.host if request.client else None,
        ),
    )
    if biz_domain not in principal.allowed_biz_domains:
        raise DataControlError("AUTH_SCOPE_MISMATCH")


@router.get("/operations")
async def list_operations(
    request: Request,
    biz_domain: Annotated[str, Query(min_length=2, max_length=64)],
    service: Annotated[DataControlService, Depends(get_data_control_service)],
    auth_provider: Annotated[AuthProvider, Depends(get_auth_provider)],
) -> dict[str, object]:
    await _authenticate_discovery(request, auth_provider, biz_domain)
    return {"contract_version": "1.0", "operations": service.describe_operations()}


@router.get("/operations/{operation}/schema")
async def operation_schema(
    operation: Operation,
    request: Request,
    biz_domain: Annotated[str, Query(min_length=2, max_length=64)],
    auth_provider: Annotated[AuthProvider, Depends(get_auth_provider)],
) -> dict[str, object]:
    await _authenticate_discovery(request, auth_provider, biz_domain)
    return {
        "contract_version": "1.0",
        "operation": operation.value,
        "request_schema": DataRequest.model_json_schema(),
    }
