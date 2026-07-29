from abc import ABC, abstractmethod
from dataclasses import dataclass

from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass(frozen=True)
class AdapterCapabilities:
    operations: frozenset[Operation]
    supports_transactions: bool
    supports_cursor_pagination: bool
    timeout_ms: int


@dataclass(frozen=True)
class AdapterHealth:
    status: str
    details: dict[str, str]


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


class ControlledInMemoryAdapter(DataAdapter):
    def __init__(
        self,
        *,
        name: str,
        target: DataTarget,
        operations: frozenset[Operation],
        supports_transactions: bool,
        supports_cursor_pagination: bool,
    ) -> None:
        self.name = name
        self.target = target
        self._capabilities = AdapterCapabilities(
            operations=operations,
            supports_transactions=supports_transactions,
            supports_cursor_pagination=supports_cursor_pagination,
            timeout_ms=5000,
        )
        self._store: dict[tuple[str, str, str, str], dict[str, object]] = {}

    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            status="UP", details={"adapter": self.name, "mode": "in_memory_phase1"}
        )

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        if command.operation not in self._capabilities.operations:
            from data_control_service.domain.exceptions import DataControlError

            raise DataControlError("OPERATION_NOT_SUPPORTED")

        tenant_id, biz_domain = command.scope
        if tenant_id != context.tenant_id or biz_domain != context.biz_domain:
            from data_control_service.domain.exceptions import DataControlError

            raise DataControlError("AUTH_SCOPE_MISMATCH")

        resource_id = str(
            command.validated_payload.get("resource_id")
            or command.validated_payload.get("data", {}).get("id")
            or "default"
        )
        key = (tenant_id, biz_domain, command.logical_resource, resource_id)

        if command.operation == Operation.GET:
            item = self._store.get(key)
            if item is None:
                from data_control_service.domain.exceptions import DataControlError

                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(
                status="OK", data=item, affected_count=1, adapter_metadata=self._metadata()
            )
        if command.operation in {Operation.LIST, Operation.SEARCH}:
            items = [
                value
                for stored_key, value in self._store.items()
                if stored_key[:3] == (tenant_id, biz_domain, command.logical_resource)
            ]
            limit = int(command.validated_payload.get("options", {}).get("limit", 50))
            return AdapterResult(
                status="OK",
                data=items[:limit],
                affected_count=len(items[:limit]),
                has_more=len(items) > limit,
                adapter_metadata=self._metadata(),
            )
        if command.operation in {
            Operation.CREATE,
            Operation.UPDATE,
            Operation.UPSERT,
            Operation.LOCK,
            Operation.UNLOCK,
        }:
            body = dict(command.validated_payload.get("data", {}))
            body.update(
                {"tenant_id": tenant_id, "biz_domain": biz_domain, "resource_id": resource_id}
            )
            self._store[key] = body
            return AdapterResult(
                status="OK",
                data={"resource_id": resource_id},
                affected_count=1,
                resource_version="v1",
                adapter_metadata=self._metadata(),
            )
        if command.operation == Operation.DELETE:
            existed = self._store.pop(key, None) is not None
            return AdapterResult(
                status="OK",
                data={"deleted": existed},
                affected_count=1 if existed else 0,
                adapter_metadata=self._metadata(),
            )
        if command.operation == Operation.BATCH:
            items = command.validated_payload.get("data", {}).get("items", [])
            return AdapterResult(
                status="OK",
                data={"items": [{"status": "OK"} for _ in items]},
                affected_count=len(items),
                adapter_metadata=self._metadata(),
            )

        from data_control_service.domain.exceptions import DataControlError

        raise DataControlError("OPERATION_NOT_SUPPORTED")

    def _metadata(self) -> dict[str, object]:
        return {"adapter": self.name, "target": self.target.value}
