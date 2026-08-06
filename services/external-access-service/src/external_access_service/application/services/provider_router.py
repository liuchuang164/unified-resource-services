from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.application.provider_runtime.routing import ProviderRoutingEngine
from external_access_service.domain.errors import ProviderNotFound
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


class ProviderRouter:
    def __init__(
        self,
        providers: tuple[ExternalProviderPort, ...],
        routing_engine: ProviderRoutingEngine | None = None,
    ) -> None:
        self._providers = {provider.provider_code(): provider for provider in providers}
        self.routing_engine = routing_engine

    def resolve(self, provider_code: ProviderCode) -> ExternalProviderPort:
        try:
            return self._providers[provider_code]
        except KeyError as exc:
            raise ProviderNotFound("Provider is not registered") from exc

    def resolve_candidates(self, request: ExternalDispatchRequest) -> list[ExternalProviderPort]:
        if self.routing_engine is None:
            return [self.resolve(request.provider.provider_code)]
        candidates = [
            self.resolve(provider_code)
            for provider_code in self.routing_engine.candidates(request)
            if provider_code in self._providers
        ]
        if not candidates:
            raise ProviderNotFound("No provider route is available")
        return candidates
