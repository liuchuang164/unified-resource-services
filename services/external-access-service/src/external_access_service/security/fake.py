from dataclasses import dataclass

from external_access_service.domain.errors import (
    BizDomainScopeMismatch,
    Forbidden,
    TenantScopeMismatch,
)
from external_access_service.domain.models import ExternalDispatchRequest


@dataclass(frozen=True, slots=True)
class AuthorizationRule:
    user_id: str
    tenant_id: str
    biz_domain: str
    operation: str
    allowed: bool = True


class FakePolicy:
    def __init__(self, rules: tuple[AuthorizationRule, ...]) -> None:
        self.rules = rules

    async def authorize(self, request: ExternalDispatchRequest) -> None:
        if request.auth_context.tenant_id != request.auth_context.tenant_id.strip():
            raise TenantScopeMismatch("Trusted tenant scope is invalid")
        if request.biz_context.biz_domain != request.biz_context.biz_domain.strip():
            raise BizDomainScopeMismatch("Trusted business-domain scope is invalid")
        for rule in self.rules:
            if (
                rule.user_id == request.auth_context.user_id
                and rule.tenant_id == request.auth_context.tenant_id
                and rule.biz_domain == request.biz_context.biz_domain
                and rule.operation == request.operation
            ):
                if rule.allowed:
                    return
                raise Forbidden("Operation is denied by policy")
        raise Forbidden("Operation is not allowed for this tenant and business domain")


class InMemoryRateLimiter:
    async def check(self, request: ExternalDispatchRequest) -> None:
        return None
