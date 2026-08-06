from dataclasses import dataclass

from external_access_service.application.provider_runtime.registry import (
    ProviderRegistry,
    ProviderRuntimeStatus,
)
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    provider_code: ProviderCode
    priority: int


class ProviderRoutingEngine:
    def __init__(self, registry: ProviderRegistry, routes: tuple[ProviderRoute, ...]) -> None:
        self.registry = registry
        self.routes = routes

    def candidates(self, request: ExternalDispatchRequest) -> list[ProviderCode]:
        configured = sorted(self.routes, key=lambda item: item.priority)
        matches: list[ProviderCode] = []
        for route in configured:
            provider = self.registry.get(route.provider_code)
            if provider.status not in {
                ProviderRuntimeStatus.ENABLED,
                ProviderRuntimeStatus.DEGRADED,
            }:
                continue
            if request.operation not in provider.supported_operations:
                continue
            matches.append(provider.provider_code)
        requested = request.provider.provider_code
        if requested not in matches:
            provider = self.registry.get(requested)
            if (
                provider.status in {ProviderRuntimeStatus.ENABLED, ProviderRuntimeStatus.DEGRADED}
                and request.operation in provider.supported_operations
            ):
                matches.insert(0, requested)
        return matches
