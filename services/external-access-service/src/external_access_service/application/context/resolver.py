from collections.abc import Mapping
from typing import Any, cast

from external_access_service.application.context.trusted_context import TrustedContext
from external_access_service.domain.errors import (
    BizDomainScopeMismatch,
    InvalidRequest,
    TenantScopeMismatch,
)
from external_access_service.domain.models import (
    AuthContext,
    BizContext,
    ExternalDispatchRequest,
    RequestSource,
)


class ContextResolver:
    def __init__(self, allow_legacy_body_context: bool = True) -> None:
        self.allow_legacy_body_context = allow_legacy_body_context

    def resolve_dispatch(
        self, headers: Mapping[str, str], body: ExternalDispatchRequest
    ) -> ExternalDispatchRequest:
        trusted = self._from_headers(headers, default_source=body.request_source.value)
        if trusted is None:
            if not self.allow_legacy_body_context:
                raise InvalidRequest("Trusted context headers are required")
            trusted = TrustedContext(
                tenant_id=body.auth_context.tenant_id,
                biz_domain=body.biz_context.biz_domain,
                user_id=body.auth_context.user_id,
                caller_type=body.request_source.value,
                caller_id=body.caller_id or body.auth_context.user_id,
                trace_id=body.trace_id,
                agent_id=body.agent_id,
                tool_call_id=body.tool_call_id,
                roles=body.auth_context.roles,
                source="legacy_body",
            )
        self._assert_body_match(trusted, body)
        return body.model_copy(
            update={
                "trace_id": trusted.trace_id,
                "request_source": RequestSource(trusted.caller_type),
                "auth_context": AuthContext(
                    tenant_id=trusted.tenant_id,
                    user_id=trusted.user_id,
                    roles=trusted.roles,
                ),
                "biz_context": BizContext(
                    biz_domain=trusted.biz_domain,
                    biz_scene=body.biz_context.biz_scene,
                ),
                "caller_id": trusted.caller_id,
                "agent_id": trusted.agent_id or body.agent_id,
                "tool_call_id": trusted.tool_call_id or body.tool_call_id,
            }
        )

    def resolve_query(
        self,
        headers: Mapping[str, str],
        query: Mapping[str, Any],
        default_source: str = "BUSINESS_SERVICE",
    ) -> TrustedContext:
        trusted = self._from_headers(headers, default_source=default_source)
        if trusted is None:
            if not self.allow_legacy_body_context:
                raise InvalidRequest("Trusted context headers are required")
            tenant_id = str(query.get("tenant_id") or "")
            biz_domain = str(query.get("biz_domain") or "")
            if not tenant_id:
                raise InvalidRequest("tenant_id is required")
            if not biz_domain:
                raise InvalidRequest("biz_domain is required")
            trusted = TrustedContext(
                tenant_id=tenant_id,
                biz_domain=biz_domain,
                user_id=str(query.get("user_id") or "query-user"),
                caller_type=cast(Any, default_source),
                caller_id=str(query.get("caller_id") or query.get("user_id") or "query-user"),
                trace_id=str(query.get("trace_id") or "query-trace"),
                source="legacy_body",
            )
        self._assert_query_match(trusted, query)
        return trusted

    def resolve_tool(self, headers: Mapping[str, str], body: Any) -> Any:
        trusted = self._from_headers(headers, default_source="AGENT_TOOL")
        if trusted is None:
            if not self.allow_legacy_body_context:
                raise InvalidRequest("Trusted context headers are required")
            trusted = TrustedContext(
                tenant_id=body.tenant_id,
                biz_domain=body.biz_domain,
                user_id=body.user_id,
                caller_type="AGENT_TOOL",
                caller_id=body.agent_id,
                trace_id=body.trace_id,
                agent_id=body.agent_id,
                tool_call_id=body.tool_call_id,
                roles=("AGENT",),
                source="legacy_body",
            )
        if body.tenant_id != trusted.tenant_id:
            raise TenantScopeMismatch("Tool tenant_id conflicts with trusted context")
        if body.biz_domain != trusted.biz_domain:
            raise BizDomainScopeMismatch("Tool biz_domain conflicts with trusted context")
        return body.model_copy(
            update={
                "trace_id": trusted.trace_id,
                "tenant_id": trusted.tenant_id,
                "biz_domain": trusted.biz_domain,
                "user_id": trusted.user_id,
                "agent_id": trusted.agent_id or body.agent_id,
                "tool_call_id": trusted.tool_call_id or body.tool_call_id,
            }
        )

    @staticmethod
    def _from_headers(
        headers: Mapping[str, str], default_source: str
    ) -> TrustedContext | None:
        tenant_id = headers.get("x-tenant-id")
        biz_domain = headers.get("x-biz-domain")
        user_id = headers.get("x-user-id")
        if not tenant_id and not biz_domain and not user_id:
            return None
        missing = [
            name
            for name, value in {
                "x-tenant-id": tenant_id,
                "x-biz-domain": biz_domain,
                "x-user-id": user_id,
            }.items()
            if not value
        ]
        if missing:
            raise InvalidRequest("Trusted context headers are incomplete", {"missing": missing})
        roles = tuple(
            item.strip()
            for item in headers.get("x-roles", "").split(",")
            if item.strip()
        )
        return TrustedContext(
            tenant_id=str(tenant_id),
            biz_domain=str(biz_domain),
            user_id=str(user_id),
            caller_type=cast(Any, headers.get("x-caller-type", default_source)),
            caller_id=headers.get("x-caller-id", str(user_id)),
            trace_id=headers.get("x-trace-id", "header-trace"),
            agent_id=headers.get("x-agent-id"),
            tool_call_id=headers.get("x-tool-call-id"),
            roles=roles,
            capabilities=tuple(
                item.strip()
                for item in headers.get("x-capabilities", "").split(",")
                if item.strip()
            ),
            source="headers",
        )

    @staticmethod
    def _assert_body_match(trusted: TrustedContext, body: ExternalDispatchRequest) -> None:
        if body.auth_context.tenant_id != trusted.tenant_id:
            raise TenantScopeMismatch("Body tenant_id conflicts with trusted context")
        if body.biz_context.biz_domain != trusted.biz_domain:
            raise BizDomainScopeMismatch("Body biz_domain conflicts with trusted context")

    @staticmethod
    def _assert_query_match(trusted: TrustedContext, query: Mapping[str, Any]) -> None:
        tenant_id = query.get("tenant_id")
        biz_domain = query.get("biz_domain")
        if tenant_id is not None and tenant_id != trusted.tenant_id:
            raise TenantScopeMismatch("Query tenant_id conflicts with trusted context")
        if biz_domain is not None and biz_domain != trusted.biz_domain:
            raise BizDomainScopeMismatch("Query biz_domain conflicts with trusted context")
