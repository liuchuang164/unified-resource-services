from httpx import AsyncClient

from data_control_service.adapters.base import AdapterCapabilities, AdapterHealth, DataAdapter
from data_control_service.adapters.postgresql import InMemoryPostgreSQLAdapter
from data_control_service.adapters.registry import AdapterRegistry
from data_control_service.api.dependencies import get_data_control_service
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


class FakeAdapter(DataAdapter):
    def __init__(self, target: DataTarget, *, status: str = "UP", required: bool = True) -> None:
        self.target = target
        self.name = f"fake-{target.value.lower()}"
        self._status = status
        self._required = required

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset({Operation.GET}),
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=False,
            timeout_ms=1000,
            required=self._required,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(self._status, {}, required=self._required)

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        return AdapterResult(data={})


def fake_registry(*, failed: DataTarget | None = None, optional: bool = False) -> AdapterRegistry:
    return AdapterRegistry(
        [
            FakeAdapter(
                target,
                status="DOWN" if target == failed else "UP",
                required=not optional if target == failed else True,
            )
            for target in DataTarget
        ]
    )


async def test_ready_checks_all_components(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert "auth_provider" in body["components"]
    assert "postgresql" in body["components"]
    assert "milvus" in body["components"]


async def test_ready_reports_required_adapter_failure() -> None:
    service = get_data_control_service()
    original = service._adapter_registry
    try:
        service._adapter_registry = fake_registry(failed=DataTarget.POSTGRESQL)
        body = await service.readiness()
    finally:
        service._adapter_registry = original
    assert body["ready"] is False
    assert body["degraded"] is False
    assert body["components"]["postgresql"]["status"] == "error"


async def test_ready_reports_optional_adapter_failure_as_degraded() -> None:
    service = get_data_control_service()
    original = service._adapter_registry
    try:
        service._adapter_registry = fake_registry(failed=DataTarget.MILVUS, optional=True)
        body = await service.readiness()
    finally:
        service._adapter_registry = original
    assert body["ready"] is True
    assert body["degraded"] is True
    assert body["components"]["milvus"]["required"] is False


async def test_registry_reports_missing_required_adapter() -> None:
    registry = AdapterRegistry([InMemoryPostgreSQLAdapter()])
    result = await registry.validate()
    assert result.status == "error"
    assert any(item.startswith("missing:") for item in result.errors)


def test_registry_rejects_duplicate_target() -> None:
    from data_control_service.domain.exceptions import DataControlError

    try:
        AdapterRegistry([InMemoryPostgreSQLAdapter(), InMemoryPostgreSQLAdapter()])
    except DataControlError as exc:
        assert exc.code == "CONFIGURATION_INVALID"
    else:
        raise AssertionError("duplicate registry should fail")


async def test_registry_reports_target_mismatch() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    registry = AdapterRegistry([adapter])
    adapter.target = DataTarget.REDIS
    result = await registry.validate()
    assert result.status == "error"
    assert "mismatch:postgresql" in result.errors
