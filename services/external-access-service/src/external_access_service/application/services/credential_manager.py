from external_access_service.application.ports.protocols import (
    CredentialManagerPort,
    CredentialProviderPort,
)
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCredential


class EnvironmentCredentialManager(CredentialManagerPort):
    def __init__(self, provider: CredentialProviderPort) -> None:
        self.provider = provider

    async def resolve(self, request: ExternalDispatchRequest) -> ProviderCredential:
        return await self.provider.get_credential(request)
