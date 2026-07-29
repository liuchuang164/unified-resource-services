from dataclasses import dataclass

from file_media_stream_service.application.dto.contracts import RequestContext
from file_media_stream_service.domain.exceptions.errors import (
    PermissionDenied,
    QuotaExceeded,
    ReplayDetected,
    Unauthenticated,
)


@dataclass(frozen=True, slots=True)
class AuthorizationRule:
    caller_id: str
    tenant_id: str
    biz_domain: str
    operation: str
    resource_scope: str | None = None
    allowed: bool = False


class FakeSecurity:
    """Development security adapter with explicit rules and deny-by-default behavior."""

    def __init__(
        self,
        rules: tuple[AuthorizationRule, ...],
        valid_tokens: frozenset[str] = frozenset(),
        quotas: dict[tuple[str, str, str], int] | None = None,
    ) -> None:
        self.rules = rules
        self.valid_tokens = valid_tokens
        self.quotas = quotas or {}
        self.nonces: set[tuple[str, str, str]] = set()

    async def verify(self, context: RequestContext) -> None:
        if not context.caller_id or not context.tenant_id or not context.biz_domain:
            raise Unauthenticated("Caller identity is incomplete")

    async def verify_capability(self, context: RequestContext, operation: str) -> None:
        if context.caller_type != "agent":
            return
        if not context.capability_token or context.capability_token not in self.valid_tokens:
            raise Unauthenticated("Capability token is invalid")

    async def authorize(
        self, context: RequestContext, operation: str, resource_scope: str | None
    ) -> None:
        matching = (
            rule
            for rule in self.rules
            if rule.caller_id == context.caller_id
            and rule.tenant_id == context.tenant_id
            and rule.biz_domain == context.biz_domain
            and rule.operation == operation
            and rule.resource_scope in {None, resource_scope}
        )
        decision = next(matching, None)
        if decision is None or not decision.allowed:
            raise PermissionDenied("Operation is not authorized")

    async def check(self, context: RequestContext, operation: str) -> None:
        key = (context.tenant_id, context.biz_domain, operation)
        remaining = self.quotas.get(key)
        if remaining is not None and remaining <= 0:
            raise QuotaExceeded("Quota exceeded")
        if remaining is not None:
            self.quotas[key] = remaining - 1

    async def check_and_record(self, context: RequestContext) -> None:
        if context.caller_type == "agent" and not context.nonce:
            raise ReplayDetected("Agent calls require a nonce")
        if not context.nonce:
            return
        key = (context.tenant_id, context.caller_id, context.nonce)
        if key in self.nonces:
            raise ReplayDetected("Request nonce has already been used")
        self.nonces.add(key)
