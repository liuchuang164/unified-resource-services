from time import monotonic

from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.domain.models import ProviderCode


class ProviderHealthManager:
    def __init__(self, providers: dict[ProviderCode, ExternalProviderPort]) -> None:
        self.providers = providers
        self._last: dict[ProviderCode, dict[str, object]] = {}

    async def check(self, provider_code: ProviderCode) -> dict[str, object]:
        provider = self.providers[provider_code]
        started = monotonic()
        try:
            health = await provider.health_check()
            result: dict[str, object] = {
                "provider": provider_code.value,
                "status": "HEALTHY",
                "latency_ms": int((monotonic() - started) * 1000),
                "details": health,
            }
        except Exception as exc:
            result = {
                "provider": provider_code.value,
                "status": "UNAVAILABLE",
                "latency_ms": int((monotonic() - started) * 1000),
                "details": {"error": exc.__class__.__name__},
            }
        self._last[provider_code] = result
        return result

    async def check_all(self) -> dict[str, dict[str, object]]:
        return {
            provider_code.value: await self.check(provider_code)
            for provider_code in self.providers
        }

    def last(self, provider_code: ProviderCode) -> dict[str, object] | None:
        return self._last.get(provider_code)
