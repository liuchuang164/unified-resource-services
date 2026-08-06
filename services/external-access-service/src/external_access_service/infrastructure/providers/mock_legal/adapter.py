from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.domain.errors import OperationNotAllowed, ProviderUnavailable
from external_access_service.domain.models import (
    ExternalDispatchRequest,
    ProviderCode,
    ProviderCredential,
    ProviderResult,
    Usage,
)


class MockLegalProviderAdapter(ExternalProviderPort):
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def provider_code(self) -> ProviderCode:
        return ProviderCode.MOCK_LEGAL_PROVIDER

    def supports(self, operation: str) -> bool:
        return operation.startswith("ALI_FARUI_")

    async def execute(
        self, request: ExternalDispatchRequest, credential: ProviderCredential
    ) -> ProviderResult:
        if not self.available:
            raise ProviderUnavailable("MOCK_LEGAL_PROVIDER unavailable")
        if not self.supports(request.operation):
            raise OperationNotAllowed("MOCK_LEGAL_PROVIDER operation unsupported")
        return ProviderResult(
            data={
                "summary": f"mock legal fallback for {request.operation}",
                "items": [{"title": "mock-provider", "snippet": request.payload["query"][:64]}],
                "provider_status": "OK",
            },
            usage=Usage(
                request_count=1,
                input_units=len(str(request.payload.get("query", ""))),
                output_units=1,
                estimated_cost=0.01,
            ),
            provider_request_id="mock_provider_request",
        )

    async def health_check(self) -> dict[str, str]:
        if not self.available:
            raise ProviderUnavailable("MOCK_LEGAL_PROVIDER unavailable")
        return {"provider": self.provider_code().value, "status": "configured"}
