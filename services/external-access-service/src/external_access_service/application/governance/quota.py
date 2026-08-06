from dataclasses import dataclass
from datetime import UTC, date, datetime

from external_access_service.domain.errors import QuotaExceeded
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


@dataclass(frozen=True, slots=True)
class QuotaRule:
    tenant_id: str
    biz_domain: str
    operation: str | None = None
    provider: ProviderCode | None = None
    daily_limit: int = 100


class QuotaService:
    def __init__(self, rules: tuple[QuotaRule, ...] = ()) -> None:
        self.rules = rules
        self._counts: dict[tuple[str, str, str, str, date], int] = {}

    async def check(self, request: ExternalDispatchRequest) -> None:
        today = datetime.now(UTC).date()
        for rule in self.rules:
            if not self._matches(rule, request):
                continue
            key = (
                request.auth_context.tenant_id,
                request.biz_context.biz_domain,
                rule.operation or "*",
                rule.provider.value if rule.provider else "*",
                today,
            )
            if self._counts.get(key, 0) >= rule.daily_limit:
                raise QuotaExceeded("Daily quota is exceeded")

    async def record(self, request: ExternalDispatchRequest) -> None:
        today = datetime.now(UTC).date()
        for rule in self.rules:
            if not self._matches(rule, request):
                continue
            key = (
                request.auth_context.tenant_id,
                request.biz_context.biz_domain,
                rule.operation or "*",
                rule.provider.value if rule.provider else "*",
                today,
            )
            self._counts[key] = self._counts.get(key, 0) + 1

    @staticmethod
    def _matches(rule: QuotaRule, request: ExternalDispatchRequest) -> bool:
        return (
            rule.tenant_id == request.auth_context.tenant_id
            and rule.biz_domain == request.biz_context.biz_domain
            and (rule.operation is None or rule.operation == request.operation)
            and (rule.provider is None or rule.provider == request.provider.provider_code)
        )
