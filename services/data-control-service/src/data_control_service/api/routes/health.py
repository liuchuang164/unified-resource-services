from typing import Annotated

from fastapi import APIRouter, Depends

from data_control_service.api.dependencies import get_data_control_service
from data_control_service.application.data_control_service import DataControlService

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "UP"}


@router.get("/health/ready")
async def ready(
    service: Annotated[DataControlService, Depends(get_data_control_service)],
) -> dict[str, object]:
    adapters = await service._adapter_registry.all()[0].health()
    return {"status": "UP", "sample_adapter": adapters.details}
