from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterTransaction,
    DataAdapter,
    mapping_from,
    reject_client_scope,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass
class _TableRow:
    logical_table: str
    tenant_id: str
    biz_domain: str
    primary_key: str
    record: dict[str, Any]


class _PostgresTransaction(AdapterTransaction):
    def __init__(self, adapter: "InMemoryPostgreSQLAdapter") -> None:
        self._adapter = adapter
        self._snapshot = deepcopy(adapter._rows)

    async def commit(self) -> None:
        self._snapshot = deepcopy(self._adapter._rows)

    async def rollback(self) -> None:
        self._adapter._rows = self._snapshot


class InMemoryPostgreSQLAdapter(DataAdapter):
    name = "postgresql"
    target = DataTarget.POSTGRESQL

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], _TableRow] = {}
        self.execute_count = 0

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.LIST,
                    Operation.CREATE,
                    Operation.UPDATE,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.BATCH,
                }
            ),
            supports_transactions=True,
            supports_atomic_transaction=True,
            supports_cursor_pagination=True,
            timeout_ms=5000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def begin(self, context: ExecutionContext) -> AdapterTransaction:
        return _PostgresTransaction(self)

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        self.execute_count += 1
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        mapping = mapping_from(command)
        table = str(mapping.physical_mapping["logical_table"])
        primary_key = str(mapping.physical_mapping["primary_key"])
        data = dict(command.validated_payload.get("data", {}))
        query = dict(command.validated_payload.get("query", {}))
        reject_client_scope(data)
        tenant_id, biz_domain = command.scope
        resource_id = command.validated_payload.get("resource_id") or data.get(primary_key)
        if (
            command.operation in {Operation.UPDATE, Operation.DELETE}
            and not resource_id
            and not query
        ):
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "empty update/delete condition is rejected"
            )
        if command.operation == Operation.CREATE:
            if not resource_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "primary key is required")
            key = (table, tenant_id, biz_domain, str(resource_id))
            if key in self._rows:
                raise DataControlError("DATA_CONSTRAINT_VIOLATION")
            return self._write(key, table, tenant_id, biz_domain, primary_key, data)
        if command.operation == Operation.UPSERT:
            if not resource_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "primary key is required")
            key = (table, tenant_id, biz_domain, str(resource_id))
            return self._write(key, table, tenant_id, biz_domain, primary_key, data)
        if command.operation == Operation.GET:
            row = self._rows.get((table, tenant_id, biz_domain, str(resource_id)))
            if row is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(status="OK", data=row.record, affected_count=1)
        if command.operation == Operation.LIST:
            rows = [
                row.record
                for key, row in self._rows.items()
                if key[:3] == (table, tenant_id, biz_domain)
            ]
            limit = int(command.validated_payload.get("options", {}).get("limit", 50))
            return AdapterResult(
                status="OK",
                data=rows[:limit],
                affected_count=len(rows[:limit]),
                has_more=len(rows) > limit,
            )
        if command.operation == Operation.UPDATE:
            key = (table, tenant_id, biz_domain, str(resource_id))
            row = self._rows.get(key)
            if row is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            merged = {**row.record, **data, "tenant_id": tenant_id, "biz_domain": biz_domain}
            return self._write(key, table, tenant_id, biz_domain, primary_key, merged)
        if command.operation == Operation.DELETE:
            existed = self._rows.pop((table, tenant_id, biz_domain, str(resource_id)), None)
            return AdapterResult(
                status="OK",
                data={"deleted": existed is not None},
                affected_count=int(existed is not None),
            )
        if command.operation == Operation.BATCH:
            items = command.validated_payload.get("data", {}).get("items", [])
            return AdapterResult(
                status="OK",
                data={"items": [{"success": True} for _ in items]},
                affected_count=len(items),
            )
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    def _write(
        self,
        key: tuple[str, str, str, str],
        table: str,
        tenant_id: str,
        biz_domain: str,
        primary_key: str,
        data: dict[str, Any],
    ) -> AdapterResult:
        record = {**data, "tenant_id": tenant_id, "biz_domain": biz_domain, primary_key: key[3]}
        self._rows[key] = _TableRow(table, tenant_id, biz_domain, primary_key, record)
        return AdapterResult(
            status="OK", data={"resource_id": key[3]}, affected_count=1, resource_version="v1"
        )
