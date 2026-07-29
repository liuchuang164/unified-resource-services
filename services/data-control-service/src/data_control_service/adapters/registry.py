from data_control_service.adapters.base import DataAdapter
from data_control_service.adapters.milvus import MilvusAdapter
from data_control_service.adapters.minio import MinIOAdapter
from data_control_service.adapters.neo4j import Neo4jAdapter
from data_control_service.adapters.postgresql import PostgreSQLAdapter
from data_control_service.adapters.redis import RedisAdapter
from data_control_service.adapters.timescaledb import TimescaleDBAdapter
from data_control_service.contracts.enums import DataTarget
from data_control_service.domain.exceptions import DataControlError


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

    def all(self) -> list[DataAdapter]:
        return list(self._by_target.values())


def create_default_registry() -> AdapterRegistry:
    return AdapterRegistry(
        [
            PostgreSQLAdapter(),
            MinIOAdapter(),
            RedisAdapter(),
            Neo4jAdapter(),
            MilvusAdapter(),
            TimescaleDBAdapter(),
        ]
    )
