from uuid import uuid4

from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext
from data_control_service.ports.auth_provider import AuthenticatedPrincipal, RequestContext


class ContextResolver:
    def resolve(
        self,
        request: DataRequest,
        principal: AuthenticatedPrincipal,
        request_context: RequestContext,
    ) -> ExecutionContext:
        declared = request.auth_context
        if not principal.subject_id or not principal.tenant_id:
            raise DataControlError("AUTH_REQUIRED")
        if declared.tenant_id != principal.tenant_id:
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        if declared.biz_domain not in principal.allowed_biz_domains:
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        if declared.actor.id != principal.subject_id:
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        trace_id = request.trace_id or request_context.trace_id or f"trace_{uuid4().hex}"
        return ExecutionContext(
            tenant_id=principal.tenant_id,
            biz_domain=declared.biz_domain,
            subject_id=principal.subject_id,
            subject_type=principal.subject_type,
            roles=principal.roles,
            permissions=principal.permissions,
            source=request.source.value,
            request_id=request.request_id,
            trace_id=trace_id,
            authenticated=True,
            credential_source=principal.credential_source,
        )
