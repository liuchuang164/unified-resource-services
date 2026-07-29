from typing import Protocol

from data_control_service.contracts.request import DataRequest
from data_control_service.domain.models import AdapterResult, ExecutionContext, RouteDecision


class AuditRepository(Protocol):
    async def record_access(
        self,
        request: DataRequest,
        context: ExecutionContext,
        *,
        status: str,
        code: str,
        latency_ms: int,
        route: RouteDecision | None = None,
    ) -> None: ...

    async def record_change(
        self,
        request: DataRequest,
        context: ExecutionContext,
        result: AdapterResult,
        *,
        status: str,
        code: str,
        route: RouteDecision,
    ) -> None: ...

    async def health(self) -> dict[str, str]: ...
