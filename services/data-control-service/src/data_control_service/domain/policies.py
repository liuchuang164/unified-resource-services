from dataclasses import dataclass

from data_control_service.contracts.enums import DataTarget, Operation


@dataclass(frozen=True)
class ResourceDefinition:
    resource_type: str
    logical_name: str
    target: DataTarget
    allowed_operations: frozenset[Operation]
    read_permission: str
    write_permission: str
    high_risk_operations: frozenset[Operation] = frozenset()
    data_constraints: dict[str, object] | None = None


@dataclass(frozen=True)
class ResourceMapping:
    tenant_id: str
    biz_domain: str
    definition: ResourceDefinition
    physical_mapping: dict[str, object]
    required: bool = True


class ResourceRegistry:
    def __init__(self, mappings: list[ResourceMapping]) -> None:
        self._mappings = {
            (
                mapping.tenant_id,
                mapping.biz_domain,
                mapping.definition.target,
                mapping.definition.resource_type,
                mapping.definition.logical_name,
            ): mapping
            for mapping in mappings
        }

    def get(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        target: DataTarget,
        resource_type: str,
        logical_name: str,
    ) -> ResourceMapping | None:
        return self._mappings.get((tenant_id, biz_domain, target, resource_type, logical_name))

    def list_mappings(self) -> tuple[ResourceMapping, ...]:
        return tuple(self._mappings.values())


def create_default_resource_registry() -> ResourceRegistry:
    return ResourceRegistry(
        [
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="DOCUMENT_RECORD",
                    logical_name="record",
                    target=DataTarget.POSTGRESQL,
                    allowed_operations=frozenset(
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
                    read_permission="data:record:read",
                    write_permission="data:record:write",
                    high_risk_operations=frozenset({Operation.DELETE, Operation.BATCH}),
                    data_constraints={"primary_key": "id", "logical_table": "document_records"},
                ),
                physical_mapping={"logical_table": "document_records", "primary_key": "id"},
            ),
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="OBJECT_ASSET",
                    logical_name="asset",
                    target=DataTarget.MINIO,
                    allowed_operations=frozenset(
                        {Operation.GET, Operation.LIST, Operation.CREATE, Operation.DELETE}
                    ),
                    read_permission="data:object:read",
                    write_permission="data:object:write",
                    high_risk_operations=frozenset({Operation.DELETE}),
                    data_constraints={
                        "bucket": "dcs-object-assets",
                        "allowed_content_types": ["text/plain", "application/json"],
                    },
                ),
                physical_mapping={"bucket": "dcs-object-assets"},
            ),
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="CACHE_ENTRY",
                    logical_name="cache",
                    target=DataTarget.REDIS,
                    allowed_operations=frozenset(
                        {
                            Operation.GET,
                            Operation.UPSERT,
                            Operation.DELETE,
                            Operation.LOCK,
                            Operation.UNLOCK,
                        }
                    ),
                    read_permission="data:cache:read",
                    write_permission="data:cache:write",
                ),
                physical_mapping={"namespace": "dcs"},
            ),
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="GRAPH_ENTITY",
                    logical_name="entity",
                    target=DataTarget.NEO4J,
                    allowed_operations=frozenset(
                        {
                            Operation.GET,
                            Operation.SEARCH,
                            Operation.CREATE,
                            Operation.UPDATE,
                            Operation.DELETE,
                            Operation.BATCH,
                        }
                    ),
                    read_permission="data:graph:read",
                    write_permission="data:graph:write",
                    high_risk_operations=frozenset({Operation.DELETE, Operation.BATCH}),
                    data_constraints={
                        "labels": ["Entity", "Document"],
                        "relations": ["RELATED_TO", "MENTIONS"],
                    },
                ),
                physical_mapping={"graph": "default"},
            ),
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="VECTOR_ITEM",
                    logical_name="embedding",
                    target=DataTarget.MILVUS,
                    allowed_operations=frozenset(
                        {Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE}
                    ),
                    read_permission="data:vector:read",
                    write_permission="data:vector:write",
                    high_risk_operations=frozenset({Operation.DELETE}),
                    data_constraints={"collection": "vector_items", "dimension": 3},
                ),
                physical_mapping={"collection": "vector_items"},
            ),
            ResourceMapping(
                tenant_id="tenant_demo",
                biz_domain="demo",
                definition=ResourceDefinition(
                    resource_type="TIME_SERIES_POINT",
                    logical_name="metric",
                    target=DataTarget.TIMESCALEDB,
                    allowed_operations=frozenset(
                        {Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH}
                    ),
                    read_permission="data:timeseries:read",
                    write_permission="data:timeseries:write",
                    high_risk_operations=frozenset({Operation.BATCH}),
                    data_constraints={"hypertable": "time_series_points"},
                ),
                physical_mapping={"hypertable": "time_series_points"},
            ),
        ]
    )
