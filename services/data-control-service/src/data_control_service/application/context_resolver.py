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
        if request.source.value == "DATA_ACCESS_GATEWAY":
            self._validate_gateway_scope(request, principal)
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

    @staticmethod
    def _validate_gateway_scope(
        request: DataRequest,
        principal: AuthenticatedPrincipal,
    ) -> None:
        if principal.credential_source != "capability-token":
            raise DataControlError("AUTH_TOKEN_INVALID")
        tool_name = request.metadata.get("tool_name")
        tool_action = request.metadata.get("tool_action")
        session_id = request.metadata.get("session_id")
        task_id = request.metadata.get("task_id")
        if (
            not isinstance(tool_name, str)
            or not isinstance(tool_action, str)
            or tool_name not in principal.allowed_tools
            or f"{tool_name}:{tool_action}" not in principal.allowed_actions
            or session_id != principal.session_id
            or task_id != principal.task_id
        ):
            raise DataControlError("AUTH_SCOPE_MISMATCH")
