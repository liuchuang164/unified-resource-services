from data_control_service.contracts.enums import WRITE_OPERATIONS
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext
from data_control_service.domain.policies import ResourceMapping
from data_control_service.ports.policy_repository import PolicyRepository


class AuthorizationService:
    def __init__(self, policy_repository: PolicyRepository | None = None) -> None:
        self._policy_repository = policy_repository

    async def authorize(
        self,
        request: DataRequest,
        context: ExecutionContext,
        registration: ResourceMapping,
    ) -> None:
        if (
            context.tenant_id != request.auth_context.tenant_id
            or context.biz_domain != request.auth_context.biz_domain
        ):
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        definition = registration.definition
        if request.operation not in definition.allowed_operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")

        permissions = set(context.permissions)
        roles = set(context.roles)
        if "DATA_CONTROL_ADMIN" in roles:
            return

        required = {definition.read_permission}
        if request.operation in WRITE_OPERATIONS:
            required.add(definition.write_permission)
        if request.operation in definition.high_risk_operations:
            required.add("data:high-risk:execute")

        if not required.issubset(permissions):
            raise DataControlError("PERMISSION_DENIED")
        if self._policy_repository is not None:
            decision = await self._policy_repository.decide(
                context, registration, request.operation, request.resource.target
            )
            if not decision.allowed:
                raise DataControlError("POLICY_DENIED")
