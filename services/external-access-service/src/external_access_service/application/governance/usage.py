from typing import Protocol

from external_access_service.domain.models import (
    ExternalDispatchRequest,
    ExternalDispatchResponse,
)


class UsageRepositoryPort(Protocol):
    async def record_usage(self, record: dict[str, object]) -> None: ...

    async def query_usage(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        operation: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, object]]: ...


class UsageMeterService:
    def __init__(self, repository: UsageRepositoryPort) -> None:
        self.repository = repository

    def calculate_cost(self, response: ExternalDispatchResponse) -> float:
        return max(response.usage.estimated_cost, response.usage.request_count * 0.02)

    async def record_usage(
        self, request: ExternalDispatchRequest, response: ExternalDispatchResponse
    ) -> None:
        if response.status.value != "SUCCEEDED":
            return
        await self.repository.record_usage(
            {
                "tenant_id": request.auth_context.tenant_id,
                "biz_domain": request.biz_context.biz_domain,
                "operation": request.operation,
                "provider": request.provider.provider_code.value,
                "request_count": response.usage.request_count,
                "estimated_cost": self.calculate_cost(response),
            }
        )

    async def query_usage(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        operation: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, object]]:
        return await self.repository.query_usage(
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            operation=operation,
            provider=provider,
        )
