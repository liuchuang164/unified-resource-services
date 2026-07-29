from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from data_control_service.api.dependencies import get_data_control_service
from data_control_service.application.data_control_service import DataControlService

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "UP"}


@router.get("/health/ready")
async def ready(
    service: Annotated[DataControlService, Depends(get_data_control_service)],
    response: Response,
) -> dict[str, object]:
    body = await service.readiness()
    if body["status"] == "NOT_READY":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body
