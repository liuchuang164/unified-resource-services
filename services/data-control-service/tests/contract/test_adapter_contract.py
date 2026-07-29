import pytest

from data_control_service.adapters.registry import create_default_registry
from data_control_service.contracts.enums import DataTarget, Operation


def test_all_phase1_adapters_are_registered() -> None:
    registry = create_default_registry()
    targets = set(registry.list_targets())
    assert targets == {
        DataTarget.POSTGRESQL,
        DataTarget.MINIO,
        DataTarget.REDIS,
        DataTarget.NEO4J,
        DataTarget.MILVUS,
        DataTarget.TIMESCALEDB,
    }


@pytest.mark.parametrize(
    ("target", "operation"),
    [
        (DataTarget.POSTGRESQL, Operation.BATCH),
        (DataTarget.MINIO, Operation.LIST),
        (DataTarget.REDIS, Operation.LOCK),
        (DataTarget.NEO4J, Operation.SEARCH),
        (DataTarget.MILVUS, Operation.SEARCH),
        (DataTarget.TIMESCALEDB, Operation.SEARCH),
    ],
)
def test_adapter_capability_matrix(target: DataTarget, operation: Operation) -> None:
    adapter = create_default_registry().get_by_target(target)
    assert operation in adapter.capabilities().operations
