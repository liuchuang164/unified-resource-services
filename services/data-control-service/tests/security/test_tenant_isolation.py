import pytest

from data_control_service.adapters.postgresql import InMemoryPostgreSQLAdapter
from data_control_service.contracts.enums import Operation
from data_control_service.domain.exceptions import DataControlError
from tests.integration.test_transaction_orchestrator import command
from tests.unit.application.test_idempotency_concurrency import context


async def test_postgresql_get_is_scoped_by_tenant_and_domain() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    await adapter.execute(command(Operation.CREATE, {"id": "doc"}), context())
    cross_scope = command(Operation.GET, {"id": "doc"})
    cross_scope = type(cross_scope)(
        operation=cross_scope.operation,
        logical_resource=cross_scope.logical_resource,
        validated_payload={**cross_scope.validated_payload, "resource_id": "doc"},
        scope=("tenant_other", "demo"),
        timeout_ms=cross_scope.timeout_ms,
        route_id=cross_scope.route_id,
    )
    with pytest.raises(DataControlError):
        await adapter.execute(cross_scope, context("tenant_other", "demo"))
