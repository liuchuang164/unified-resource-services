from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from external_access_service.domain.errors import ProviderNotFound
from external_access_service.domain.models import ProviderCode


class ProviderRuntimeStatus(StrEnum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ExternalProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_code: ProviderCode
    name: str
    status: ProviderRuntimeStatus = ProviderRuntimeStatus.REGISTERED
    supported_operations: tuple[str, ...] = ()
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProviderRegistry:
    def __init__(self, providers: tuple[ExternalProvider, ...] = ()) -> None:
        self._providers = {provider.provider_code: provider for provider in providers}

    def register(self, provider: ExternalProvider) -> None:
        self._providers[provider.provider_code] = provider

    def get(self, provider_code: ProviderCode) -> ExternalProvider:
        try:
            return self._providers[provider_code]
        except KeyError as exc:
            raise ProviderNotFound("Provider is not registered") from exc

    def list_providers(self) -> list[ExternalProvider]:
        return list(self._providers.values())

    def enabled_for_operation(self, operation: str) -> list[ExternalProvider]:
        return [
            provider
            for provider in self._providers.values()
            if provider.status in {ProviderRuntimeStatus.ENABLED, ProviderRuntimeStatus.DEGRADED}
            and operation in provider.supported_operations
        ]

    def update_status(
        self, provider_code: ProviderCode, status: ProviderRuntimeStatus
    ) -> ExternalProvider:
        provider = self.get(provider_code)
        updated = provider.model_copy(update={"status": status})
        self.register(updated)
        return updated
