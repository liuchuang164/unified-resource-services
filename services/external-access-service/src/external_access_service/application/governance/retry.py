from dataclasses import dataclass

from external_access_service.domain.errors import (
    DomainError,
    ProviderRateLimited,
    ProviderUnavailable,
)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float = 0
    reason: str | None = None


class RetryPolicyService:
    def decide(self, error: DomainError, attempt: int, max_attempts: int) -> RetryDecision:
        if attempt >= max_attempts:
            return RetryDecision(False)
        if isinstance(error, ProviderRateLimited):
            retry_after = error.details.get("retry_after_seconds") or error.details.get(
                "retry_after"
            )
            delay = self._parse_retry_after(retry_after)
            return RetryDecision(True, min(delay, 0.2), "provider_rate_limited")
        if isinstance(error, ProviderUnavailable):
            return RetryDecision(True, min(0.05 * (2 ** (attempt - 1)), 0.2), "provider_5xx")
        if error.retryable:
            return RetryDecision(True, min(0.05 * (2 ** (attempt - 1)), 0.2), "retryable_error")
        return RetryDecision(False)

    @staticmethod
    def _parse_retry_after(value: object) -> float:
        try:
            return max(0.0, float(str(value)))
        except (TypeError, ValueError):
            return 0.05
