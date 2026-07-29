from dataclasses import dataclass
from typing import Protocol

from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.models import ExecutionContext
from data_control_service.domain.policies import ResourceMapping


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    policy_id: str | None
    effect: str


class PolicyRepository(Protocol):
    async def decide(
        self,
        context: ExecutionContext,
        mapping: ResourceMapping,
        operation: Operation,
        target: DataTarget,
    ) -> PolicyDecision: ...

    async def health(self) -> dict[str, str]: ...
