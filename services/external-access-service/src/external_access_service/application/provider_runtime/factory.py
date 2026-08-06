from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.domain.models import ProviderCode


class ProviderAdapterFactory:
    def __init__(self, providers: dict[ProviderCode, ExternalProviderPort]) -> None:
        self.providers = providers

    def create(self, provider_code: ProviderCode) -> ExternalProviderPort:
        return self.providers[provider_code]
