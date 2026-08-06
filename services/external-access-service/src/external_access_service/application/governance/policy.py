from dataclasses import dataclass

from external_access_service.application.ports.protocols import PolicyPort
from external_access_service.domain.errors import (
    BizDomainScopeMismatch,
    Forbidden,
    OperationNotAllowed,
    TenantScopeMismatch,
)
from external_access_service.domain.models import ExternalDispatchRequest


@dataclass(frozen=True, slots=True)
class PolicyRule:
    tenant_id: str
    biz_domain: str
    operation: str
    role: str | None = None
    allowed: bool = True


class PolicyService(PolicyPort):
    def __init__(self, rules: tuple[PolicyRule, ...]) -> None:
        self.rules = rules

    async def authorize(self, request: ExternalDispatchRequest) -> None:
        self.check_tenant_policy(request)
        self.check_operation_access(request)

    def check_tenant_policy(self, request: ExternalDispatchRequest) -> None:
        if not request.auth_context.tenant_id:
            raise TenantScopeMismatch("Tenant scope is required")
        if not request.biz_context.biz_domain:
            raise BizDomainScopeMismatch("Business-domain scope is required")

    def check_operation_access(self, request: ExternalDispatchRequest) -> None:
        roles = set(request.auth_context.roles)
        for rule in self.rules:
            if (
                rule.tenant_id == request.auth_context.tenant_id
                and rule.biz_domain == request.biz_context.biz_domain
                and rule.operation == request.operation
                and (rule.role is None or rule.role in roles)
            ):
                if rule.allowed:
                    return
                raise OperationNotAllowed("Operation is denied by policy")
        raise Forbidden("Operation is not allowed for this tenant and business domain")
