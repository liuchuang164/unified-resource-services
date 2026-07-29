from uuid import uuid4

from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext


class ContextResolver:
    def resolve(self, request: DataRequest) -> ExecutionContext:
        auth = request.auth_context
        if not auth.subject_id or not auth.tenant_id or not auth.biz_domain:
            raise DataControlError("AUTH_REQUIRED")
        trace_id = request.trace_id or f"trace_{uuid4().hex}"
        return ExecutionContext(
            tenant_id=auth.tenant_id,
            biz_domain=auth.biz_domain,
            subject_id=auth.subject_id,
            subject_type=auth.subject_type.value,
            roles=tuple(auth.roles),
            permissions=tuple(auth.permissions),
            source=request.source.value,
            request_id=request.request_id,
            trace_id=trace_id,
        )
