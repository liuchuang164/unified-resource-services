from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.domain.errors import ProviderNotFound
from external_access_service.domain.models import ProviderCode


class ProviderRouter:
    def __init__(self, providers: tuple[ExternalProviderPort, ...]) -> None:
        self._providers = {provider.provider_code(): provider for provider in providers}

    def resolve(self, provider_code: ProviderCode) -> ExternalProviderPort:
        try:
            return self._providers[provider_code]
        except KeyError as exc:
            raise ProviderNotFound("Provider is not registered") from exc
