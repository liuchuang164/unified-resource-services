from external_access_service.application.provider_runtime.registry import (
    ExternalProvider,
    ProviderRegistry,
    ProviderRuntimeStatus,
)
from external_access_service.domain.models import ProviderCode


class ProviderLifecycleManager:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def enable_provider(self, provider_code: ProviderCode) -> ExternalProvider:
        return self.registry.update_status(provider_code, ProviderRuntimeStatus.ENABLED)

    def disable_provider(self, provider_code: ProviderCode) -> ExternalProvider:
        return self.registry.update_status(provider_code, ProviderRuntimeStatus.DISABLED)

    def mark_degraded(self, provider_code: ProviderCode) -> ExternalProvider:
        return self.registry.update_status(provider_code, ProviderRuntimeStatus.DEGRADED)

    def mark_unavailable(self, provider_code: ProviderCode) -> ExternalProvider:
        return self.registry.update_status(provider_code, ProviderRuntimeStatus.UNAVAILABLE)
