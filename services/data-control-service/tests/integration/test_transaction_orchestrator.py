import pytest

from data_control_service.adapters.postgresql import InMemoryPostgreSQLAdapter
from data_control_service.application.transaction_orchestrator import TransactionOrchestrator
from data_control_service.contracts.enums import Operation, TransactionMode
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand
from tests.unit.application.test_idempotency_concurrency import context


def command(operation: Operation, data: dict[str, object]) -> AdapterCommand:
    from data_control_service.domain.policies import create_default_resource_registry

    mapping = create_default_resource_registry().list_mappings()[0]
    return AdapterCommand(
        operation=operation,
        logical_resource="DOCUMENT_RECORD:record",
        validated_payload={
            "data": data,
            "query": {},
            "options": {},
            "resource_id": data.get("id"),
            "resource_mapping": mapping,
        },
        scope=("tenant_demo", "demo"),
        timeout_ms=5000,
        route_id="route_test",
    )


async def test_none_executes_single_request() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    result = await TransactionOrchestrator().execute(
        adapter=adapter,
        command=command(Operation.CREATE, {"id": "one"}),
        context=context(),
        mode=TransactionMode.NONE,
    )
    assert result.affected_count == 1


async def test_atomic_rolls_back_on_failure() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    batch = command(
        Operation.BATCH,
        {
            "items": [
                {"operation": "CREATE", "data": {"id": "one"}},
                {"operation": "CREATE", "data": {}},
            ]
        },
    )
    with pytest.raises(DataControlError):
        await TransactionOrchestrator().execute(
            adapter=adapter, command=batch, context=context(), mode=TransactionMode.ATOMIC
        )
    with pytest.raises(DataControlError):
        await adapter.execute(command(Operation.GET, {"id": "one"}), context())


async def test_best_effort_returns_ordered_item_results() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    batch = command(
        Operation.BATCH,
        {
            "items": [
                {"operation": "CREATE", "data": {"id": "one"}},
                {"operation": "CREATE", "data": {}},
            ]
        },
    )
    result = await TransactionOrchestrator().execute(
        adapter=adapter, command=batch, context=context(), mode=TransactionMode.BEST_EFFORT
    )
    assert result.data["total"] == 2
    assert result.data["succeeded"] == 1
    assert result.data["failed"] == 1
    assert [item["index"] for item in result.data["items"]] == [0, 1]
