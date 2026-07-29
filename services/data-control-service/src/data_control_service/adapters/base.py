from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass(frozen=True)
class AdapterCapabilities:
    operations: frozenset[Operation]
    supports_transactions: bool
    supports_atomic_transaction: bool
    supports_cursor_pagination: bool
    timeout_ms: int
    required: bool = True


@dataclass(frozen=True)
class AdapterHealth:
    status: str
    details: dict[str, str]
    required: bool = True


class AdapterTransaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class DataAdapter(ABC):
    name: str
    target: DataTarget

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> AdapterHealth:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        raise NotImplementedError

    async def begin(self, context: ExecutionContext) -> AdapterTransaction:
        raise NotImplementedError


def mapping_from(command: AdapterCommand) -> Any:
    return command.validated_payload["resource_mapping"]


def reject_client_scope(data: dict[str, Any]) -> None:
    from data_control_service.domain.exceptions import DataControlError

    if "tenant_id" in data or "biz_domain" in data:
        raise DataControlError("REQUEST_SCHEMA_INVALID", "client cannot override tenant scope")
