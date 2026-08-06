from dataclasses import dataclass
from time import monotonic

from external_access_service.domain.errors import RateLimitExceeded
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    tenant_id: str
    biz_domain: str
    operation: str | None = None
    provider: ProviderCode | None = None
    capacity: int = 10
    refill_per_second: float = 1


@dataclass(slots=True)
class BucketState:
    tokens: float
    updated_at: float


class RateLimitService:
    def __init__(self, rules: tuple[RateLimitRule, ...]) -> None:
        self.rules = rules
        self._buckets: dict[tuple[str, str, str, str], BucketState] = {}

    async def check(self, request: ExternalDispatchRequest) -> None:
        for rule in self.rules:
            if not self._matches(rule, request):
                continue
            allowed, retry_after = self.allow(rule, request)
            if not allowed:
                raise RateLimitExceeded(
                    "Rate limit exceeded",
                    {
                        "retry_after_seconds": retry_after,
                        "reason": self._key(rule, request),
                    },
                )

    def allow(self, rule: RateLimitRule, request: ExternalDispatchRequest) -> tuple[bool, int]:
        key = self._key(rule, request)
        now = monotonic()
        bucket = self._buckets.setdefault(key, BucketState(rule.capacity, now))
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(rule.capacity, bucket.tokens + elapsed * rule.refill_per_second)
        bucket.updated_at = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True, 0
        retry_after = int(max(1.0, (1 - bucket.tokens) / rule.refill_per_second))
        return False, retry_after

    @staticmethod
    def _matches(rule: RateLimitRule, request: ExternalDispatchRequest) -> bool:
        return (
            rule.tenant_id == request.auth_context.tenant_id
            and rule.biz_domain == request.biz_context.biz_domain
            and (rule.operation is None or rule.operation == request.operation)
            and (rule.provider is None or rule.provider == request.provider.provider_code)
        )

    @staticmethod
    def _key(rule: RateLimitRule, request: ExternalDispatchRequest) -> tuple[str, str, str, str]:
        return (
            request.auth_context.tenant_id,
            request.biz_context.biz_domain,
            rule.operation or "*",
            rule.provider.value if rule.provider else "*",
        )
