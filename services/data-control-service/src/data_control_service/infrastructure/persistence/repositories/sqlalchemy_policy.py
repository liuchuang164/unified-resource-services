from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.models import ExecutionContext
from data_control_service.domain.policies import ResourceMapping
from data_control_service.infrastructure.persistence.models.policy_binding import PolicyBindingModel
from data_control_service.ports.policy_repository import PolicyDecision, PolicyRepository


class SQLAlchemyPolicyRepository(PolicyRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def decide(
        self,
        context: ExecutionContext,
        mapping: ResourceMapping,
        operation: Operation,
        target: DataTarget,
    ) -> PolicyDecision:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PolicyBindingModel)
                .where(
                    PolicyBindingModel.tenant_id == context.tenant_id,
                    PolicyBindingModel.biz_domain == context.biz_domain,
                    PolicyBindingModel.enabled.is_(True),
                )
                .order_by(PolicyBindingModel.priority.desc())
            )
            bindings = result.scalars().all()
        for binding in bindings:
            if not self._matches(binding, context, mapping, operation, target):
                continue
            return PolicyDecision(binding.effect == "ALLOW", binding.id, binding.effect)
        return PolicyDecision(False, None, "DENY")

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            await session.execute(select(PolicyBindingModel.id).limit(1))
        return {"status": "ok", "backend": "postgresql"}

    @staticmethod
    def _matches(
        binding: PolicyBindingModel,
        context: ExecutionContext,
        mapping: ResourceMapping,
        operation: Operation,
        target: DataTarget,
    ) -> bool:
        subject_match = binding.subject_pattern in {"*", context.subject_id}
        role_match = binding.role is None or binding.role in context.roles
        permission_match = binding.permission is None or binding.permission in context.permissions
        return (
            subject_match
            and role_match
            and permission_match
            and (binding.source is None or binding.source == context.source)
            and (binding.operation is None or binding.operation == operation.value)
            and (binding.target is None or binding.target == target.value)
            and (
                binding.resource_type is None
                or binding.resource_type == mapping.definition.resource_type
            )
            and (
                binding.resource_name is None
                or binding.resource_name == mapping.definition.logical_name
            )
        )
