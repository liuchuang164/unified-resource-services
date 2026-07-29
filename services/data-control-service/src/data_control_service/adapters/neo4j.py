from dataclasses import dataclass

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    mapping_from,
    reject_client_scope,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass
class _Node:
    node_id: str
    label: str
    tenant_id: str
    biz_domain: str
    properties: dict[str, object]


@dataclass
class _Relation:
    relation_id: str
    relation_type: str
    from_id: str
    to_id: str
    tenant_id: str
    biz_domain: str


class InMemoryNeo4jAdapter(DataAdapter):
    name = "neo4j"
    target = DataTarget.NEO4J

    def __init__(self) -> None:
        self._nodes: dict[tuple[str, str, str], _Node] = {}
        self._relations: dict[str, _Relation] = {}

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.SEARCH,
                    Operation.CREATE,
                    Operation.UPDATE,
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

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        data = command.validated_payload.get("data", {})
        query = command.validated_payload.get("query", {})
        reject_client_scope(data)
        if any(key in data or key in query for key in {"cypher", "raw_cypher"}):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "raw Cypher is forbidden")
        mapping = mapping_from(command)
        allowed_labels = set(mapping.definition.data_constraints.get("labels", []))
        allowed_relations = set(mapping.definition.data_constraints.get("relations", []))
        tenant_id, biz_domain = command.scope
        action = data.get("action")
        if command.operation == Operation.CREATE and action == "relation":
            relation_type = str(data.get("relation_type", ""))
            if relation_type not in allowed_relations:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "relation type is not allowed")
            from_id, to_id = str(data.get("from_id")), str(data.get("to_id"))
            left = self._nodes.get((tenant_id, biz_domain, from_id))
            right = self._nodes.get((tenant_id, biz_domain, to_id))
            if left is None or right is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            relation_id = f"rel_{len(self._relations) + 1}"
            self._relations[relation_id] = _Relation(
                relation_id, relation_type, from_id, to_id, tenant_id, biz_domain
            )
            return AdapterResult(status="OK", data={"relation_id": relation_id}, affected_count=1)
        if command.operation == Operation.CREATE:
            label = str(data.get("label", ""))
            if label not in allowed_labels:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "label is not allowed")
            node_id = str(data.get("id") or command.validated_payload.get("resource_id") or "")
            if not node_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "node id is required")
            self._nodes[(tenant_id, biz_domain, node_id)] = _Node(
                node_id,
                label,
                tenant_id,
                biz_domain,
                {**data, "tenant_id": tenant_id, "biz_domain": biz_domain},
            )
            return AdapterResult(status="OK", data={"node_id": node_id}, affected_count=1)
        if command.operation == Operation.GET:
            node_id = str(
                command.validated_payload.get("resource_id") or query.get("node_id") or ""
            )
            node = self._nodes.get((tenant_id, biz_domain, node_id))
            if node is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(status="OK", data=node.properties, affected_count=1)
        if command.operation == Operation.SEARCH:
            label = query.get("label")
            nodes = [
                node.properties
                for key, node in self._nodes.items()
                if key[:2] == (tenant_id, biz_domain) and (label is None or node.label == label)
            ]
            return AdapterResult(status="OK", data=nodes, affected_count=len(nodes))
        if command.operation == Operation.DELETE:
            node_id = str(command.validated_payload.get("resource_id") or data.get("id") or "")
            existed = self._nodes.pop((tenant_id, biz_domain, node_id), None) is not None
            return AdapterResult(
                status="OK", data={"deleted": existed}, affected_count=int(existed)
            )
        raise DataControlError("OPERATION_NOT_SUPPORTED")
