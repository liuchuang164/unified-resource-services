from data_control_service.contracts.enums import WRITE_OPERATIONS
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext
from data_control_service.domain.policies import ResourceRegistration


class AuthorizationService:
    def authorize(
        self,
        request: DataRequest,
        context: ExecutionContext,
        registration: ResourceRegistration,
    ) -> None:
        if (
            context.tenant_id != request.auth_context.tenant_id
            or context.biz_domain != request.auth_context.biz_domain
        ):
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        if context.biz_domain not in registration.allowed_biz_domains:
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        if request.operation not in registration.allowed_operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")

        permissions = set(context.permissions)
        roles = set(context.roles)
        if "DATA_CONTROL_ADMIN" in roles:
            return

        required = set(registration.required_permissions)
        if request.operation in WRITE_OPERATIONS:
            required.add(f"data:{registration.name}:write")
        if request.operation in registration.high_risk_operations:
            required.add("data:high-risk:execute")

        if not required.issubset(permissions):
            raise DataControlError("PERMISSION_DENIED")
