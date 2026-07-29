from dataclasses import dataclass

from data_control_service.contracts.enums import DataTarget, Operation


@dataclass(frozen=True)
class ResourceRegistration:
    resource_type: str
    name: str
    target: DataTarget
    allowed_operations: frozenset[Operation]
    allowed_biz_domains: frozenset[str]
    required_permissions: frozenset[str]
    high_risk_operations: frozenset[Operation] = frozenset()


RESOURCE_REGISTRY: dict[tuple[DataTarget, str, str], ResourceRegistration] = {
    (
        DataTarget.POSTGRESQL,
        "CASE_RECORD",
        "case",
    ): ResourceRegistration(
        "CASE_RECORD",
        "case",
        DataTarget.POSTGRESQL,
        frozenset(
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
        frozenset({"litigation", "default"}),
        frozenset({"data:case:read"}),
        frozenset({Operation.DELETE, Operation.BATCH}),
    ),
    (
        DataTarget.MINIO,
        "OBJECT_DOCUMENT",
        "document",
    ): ResourceRegistration(
        "OBJECT_DOCUMENT",
        "document",
        DataTarget.MINIO,
        frozenset({Operation.GET, Operation.LIST, Operation.CREATE, Operation.DELETE}),
        frozenset({"litigation", "default"}),
        frozenset({"data:object:read"}),
        frozenset({Operation.DELETE}),
    ),
    (
        DataTarget.REDIS,
        "CACHE_ENTRY",
        "cache",
    ): ResourceRegistration(
        "CACHE_ENTRY",
        "cache",
        DataTarget.REDIS,
        frozenset(
            {Operation.GET, Operation.UPSERT, Operation.DELETE, Operation.LOCK, Operation.UNLOCK}
        ),
        frozenset({"litigation", "default"}),
        frozenset({"data:cache:read"}),
    ),
    (
        DataTarget.NEO4J,
        "GRAPH_ENTITY",
        "entity",
    ): ResourceRegistration(
        "GRAPH_ENTITY",
        "entity",
        DataTarget.NEO4J,
        frozenset(
            {
                Operation.GET,
                Operation.SEARCH,
                Operation.CREATE,
                Operation.UPDATE,
                Operation.DELETE,
                Operation.BATCH,
            }
        ),
        frozenset({"litigation", "default"}),
        frozenset({"data:graph:read"}),
        frozenset({Operation.DELETE, Operation.BATCH}),
    ),
    (
        DataTarget.MILVUS,
        "VECTOR_EMBEDDING",
        "embedding",
    ): ResourceRegistration(
        "VECTOR_EMBEDDING",
        "embedding",
        DataTarget.MILVUS,
        frozenset({Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE}),
        frozenset({"litigation", "default"}),
        frozenset({"data:vector:read"}),
        frozenset({Operation.DELETE}),
    ),
    (
        DataTarget.TIMESCALEDB,
        "TIME_SERIES_METRIC",
        "metric",
    ): ResourceRegistration(
        "TIME_SERIES_METRIC",
        "metric",
        DataTarget.TIMESCALEDB,
        frozenset({Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH}),
        frozenset({"litigation", "default"}),
        frozenset({"data:timeseries:read"}),
        frozenset({Operation.BATCH}),
    ),
}
