from typing import Protocol

from external_access_service.domain.models import (
    ExternalDispatchRequest,
    ProviderCode,
    ProviderCredential,
    ProviderResult,
)


class CredentialManagerPort(Protocol):
    async def resolve(self, request: ExternalDispatchRequest) -> ProviderCredential: ...


class ExternalProviderPort(Protocol):
    def provider_code(self) -> ProviderCode: ...

    def supports(self, operation: str) -> bool: ...

    async def execute(
        self, request: ExternalDispatchRequest, credential: ProviderCredential
    ) -> ProviderResult: ...

    async def health_check(self) -> dict[str, str]: ...


class AuditSinkPort(Protocol):
    async def write(self, event: dict[str, object]) -> None: ...


class PolicyPort(Protocol):
    async def authorize(self, request: ExternalDispatchRequest) -> None: ...


class RateLimiterPort(Protocol):
    async def check(self, request: ExternalDispatchRequest) -> None: ...
