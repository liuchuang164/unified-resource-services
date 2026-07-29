from dataclasses import dataclass

from data_control_service.adapters.base import AdapterHealth, DataAdapter
from data_control_service.adapters.milvus import InMemoryMilvusAdapter
from data_control_service.adapters.minio import InMemoryMinIOAdapter
from data_control_service.adapters.neo4j import InMemoryNeo4jAdapter
from data_control_service.adapters.postgresql import InMemoryPostgreSQLAdapter
from data_control_service.adapters.redis import InMemoryRedisAdapter
from data_control_service.adapters.timescaledb import InMemoryTimescaleDBAdapter
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget
from data_control_service.domain.exceptions import DataControlError


@dataclass(frozen=True)
class RegistryValidationResult:
    status: str
    errors: tuple[str, ...] = ()


class AdapterRegistry:
    def __init__(self, adapters: list[DataAdapter]) -> None:
        self._by_target: dict[DataTarget, DataAdapter] = {}
        self._by_name: dict[str, DataAdapter] = {}
        for adapter in adapters:
            if adapter.target in self._by_target or adapter.name in self._by_name:
                raise DataControlError("CONFIGURATION_INVALID", "duplicate adapter registration")
            self._by_target[adapter.target] = adapter
            self._by_name[adapter.name] = adapter

    def get_by_target(self, target: DataTarget) -> DataAdapter:
        adapter = self._by_target.get(target)
        if adapter is None:
            raise DataControlError("ADAPTER_NOT_REGISTERED")
        return adapter

    def list_targets(self) -> tuple[DataTarget, ...]:
        return tuple(self._by_target)

    def list_adapters(self) -> tuple[DataAdapter, ...]:
        return tuple(self._by_target.values())

    async def validate(self) -> RegistryValidationResult:
        required = set(DataTarget)
        missing = sorted(target.value for target in required - set(self._by_target))
        mismatches = [
            adapter.name
            for target, adapter in self._by_target.items()
            if adapter.target != target or not adapter.capabilities().operations
        ]
        errors = tuple(
            [*(f"missing:{item}" for item in missing), *(f"mismatch:{item}" for item in mismatches)]
        )
        return RegistryValidationResult("ok" if not errors else "error", errors)

    async def health_all(self) -> dict[DataTarget, AdapterHealth]:
        return {adapter.target: await adapter.health() for adapter in self._by_target.values()}


def create_default_registry(settings: Settings | None = None) -> AdapterRegistry:
    settings = settings or Settings()
    return AdapterRegistry(
        [
            InMemoryPostgreSQLAdapter(),
            InMemoryMinIOAdapter(
                settings.max_object_size_bytes, settings.max_presigned_url_ttl_seconds
            ),
            InMemoryRedisAdapter(settings.max_redis_ttl_seconds),
            InMemoryNeo4jAdapter(),
            InMemoryMilvusAdapter(settings.max_vector_top_k),
            InMemoryTimescaleDBAdapter(settings.max_timeseries_query_days),
        ]
    )
