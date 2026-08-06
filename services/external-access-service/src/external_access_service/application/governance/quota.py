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


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    id: str
    tenant_id: str
    biz_domain: str
    operation: str | None
    provider: ProviderCode | None
    limit_value: int
    period: str = "DAY"
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class QuotaPolicyRepository:
    def __init__(self, policies: tuple[QuotaPolicy, ...] = ()) -> None:
        self._policies = list(policies)

    async def list_enabled(
        self, tenant_id: str, biz_domain: str
    ) -> tuple[QuotaPolicy, ...]:
        return tuple(
            policy
            for policy in self._policies
            if policy.enabled
            and policy.tenant_id == tenant_id
            and policy.biz_domain == biz_domain
        )

    async def upsert(self, policy: QuotaPolicy) -> None:
        self._policies = [item for item in self._policies if item.id != policy.id]
        self._policies.append(policy)


class QuotaService:
    def __init__(
        self,
        rules: tuple[QuotaRule, ...] = (),
        repository: QuotaPolicyRepository | None = None,
    ) -> None:
        self.rules = rules
        self.repository = repository
        self._counts: dict[tuple[str, str, str, str, date], int] = {}

    async def check(self, request: ExternalDispatchRequest) -> None:
        today = datetime.now(UTC).date()
        for rule in await self._rules(request):
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
        for rule in await self._rules(request):
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

    async def _rules(self, request: ExternalDispatchRequest) -> tuple[QuotaRule, ...]:
        if self.repository is None:
            return self.rules
        policies = await self.repository.list_enabled(
            request.auth_context.tenant_id,
            request.biz_context.biz_domain,
        )
        repository_rules = tuple(
            QuotaRule(
                tenant_id=policy.tenant_id,
                biz_domain=policy.biz_domain,
                operation=policy.operation,
                provider=policy.provider,
                daily_limit=policy.limit_value,
            )
            for policy in policies
        )
        return self.rules + repository_rules

    @staticmethod
    def _matches(rule: QuotaRule, request: ExternalDispatchRequest) -> bool:
        return (
            rule.tenant_id == request.auth_context.tenant_id
            and rule.biz_domain == request.biz_context.biz_domain
            and (rule.operation is None or rule.operation == request.operation)
            and (rule.provider is None or rule.provider == request.provider.provider_code)
        )
