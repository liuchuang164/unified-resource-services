from collections.abc import Callable

import httpx
import pytest
from conftest import container_with_transport

from external_access_service.application.audit import AuditEventPublisher
from external_access_service.application.governance import (
    CircuitBreakerService,
    CircuitState,
    QuotaPolicy,
    QuotaPolicyRepository,
    QuotaService,
    RateLimitRule,
    RateLimitService,
)
from external_access_service.domain.errors import ProviderUnavailable
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


class FailingAuditPublisher(AuditEventPublisher):
    async def publish(self, event: dict[str, object]) -> None:
        raise RuntimeError("audit sink down")


@pytest.mark.asyncio
async def test_audit_publisher_failure_does_not_affect_business(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    container.entry.audit_publisher = FailingAuditPublisher()
    response = await container.entry.dispatch(dispatch_request(request_id="req_audit_publish"))
    assert response.status.value == "SUCCEEDED"


@pytest.mark.asyncio
async def test_quota_policy_repository_enforces_operation_quota(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    quota = QuotaService(
        repository=QuotaPolicyRepository(
            (
                QuotaPolicy(
                    id="quota-1",
                    tenant_id="tenant_A",
                    biz_domain="LEGAL",
                    operation="ALI_FARUI_LEGAL_RESEARCH_FULL",
                    provider=ProviderCode.ALI_FARUI,
                    limit_value=1,
                ),
            )
        )
    )
    request = dispatch_request()
    await quota.check(request)
    await quota.record(request)
    with pytest.raises(Exception) as exc:
        await quota.check(request)
    assert exc.value.__class__.__name__ == "QuotaExceeded"


@pytest.mark.asyncio
async def test_rate_limit_token_consumption_and_retry_after(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    limiter = RateLimitService(
        (
            RateLimitRule(
                tenant_id="tenant_A",
                biz_domain="LEGAL",
                provider=ProviderCode.ALI_FARUI,
                capacity=1,
                refill_per_second=0.1,
            ),
        )
    )
    request = dispatch_request()
    await limiter.check(request)
    with pytest.raises(Exception) as exc:
        await limiter.check(request)
    assert exc.value.__class__.__name__ == "RateLimitExceeded"
    assert exc.value.details["retry_after_seconds"] >= 1


@pytest.mark.asyncio
async def test_circuit_breaker_open_half_open_and_recovery() -> None:
    breaker = CircuitBreakerService(failure_threshold=1, recovery_seconds=0)
    await breaker.record_failure(
        ProviderCode.ALI_FARUI,
        ProviderUnavailable("provider failed"),
    )
    assert breaker.state(ProviderCode.ALI_FARUI) == CircuitState.OPEN
    await breaker.before_call(ProviderCode.ALI_FARUI)
    assert breaker.state(ProviderCode.ALI_FARUI) == CircuitState.HALF_OPEN
    await breaker.record_success(ProviderCode.ALI_FARUI)
    assert breaker.state(ProviderCode.ALI_FARUI) == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_retry_after_header_is_used_for_429(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "slow"})
        return httpx.Response(200, json={"data": {"answer": "ok"}})

    container = container_with_transport(handler)
    response = await container.entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert attempts["count"] == 2
    assert container.audit.events[-1]["retry_reason"] == "provider_rate_limited"


@pytest.mark.asyncio
async def test_400_does_not_retry(dispatch_request: Callable[..., ExternalDispatchRequest]) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, json={"error": "bad"})

    container = container_with_transport(handler)
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == "PROVIDER_BAD_RESPONSE"
    assert attempts["count"] == 1
