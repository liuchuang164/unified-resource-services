import math
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
class _Vector:
    vector_id: str
    tenant_id: str
    biz_domain: str
    values: list[float]
    metadata: dict[str, object]


class InMemoryMilvusAdapter(DataAdapter):
    name = "milvus"
    target = DataTarget.MILVUS

    def __init__(self, max_top_k: int = 20) -> None:
        self._vectors: dict[tuple[str, str, str], _Vector] = {}
        self._max_top_k = max_top_k

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE}
            ),
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=False,
            timeout_ms=5000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        data = command.validated_payload.get("data", {})
        query = command.validated_payload.get("query", {})
        reject_client_scope(data)
        if "collection" in data or "physical_collection" in data or "expr" in query:
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "physical collection and raw expressions are forbidden"
            )
        mapping = mapping_from(command)
        dimension = int(mapping.definition.data_constraints["dimension"])
        tenant_id, biz_domain = command.scope
        if command.operation in {Operation.CREATE, Operation.UPSERT}:
            values = [float(item) for item in data.get("vector", [])]
            if len(values) != dimension:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "vector dimension mismatch")
            metadata = dict(data.get("metadata", {}))
            if not set(metadata).issubset({"source", "category"}):
                raise DataControlError("REQUEST_SCHEMA_INVALID", "metadata field is not allowed")
            vector_id = str(data.get("id") or command.validated_payload.get("resource_id") or "")
            if not vector_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "vector id is required")
            self._vectors[(tenant_id, biz_domain, vector_id)] = _Vector(
                vector_id, tenant_id, biz_domain, values, metadata
            )
            return AdapterResult(status="OK", data={"vector_id": vector_id}, affected_count=1)
        if command.operation == Operation.SEARCH:
            vector = [float(item) for item in query.get("vector", [])]
            top_k = int(query.get("top_k", 10))
            if len(vector) != dimension or top_k < 1 or top_k > self._max_top_k:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "invalid vector search request")
            scored = [
                {
                    "vector_id": item.vector_id,
                    "score": _cosine(vector, item.values),
                    "metadata": item.metadata,
                }
                for key, item in self._vectors.items()
                if key[:2] == (tenant_id, biz_domain)
            ]
            scored.sort(key=lambda item: _as_float(item["score"]), reverse=True)
            return AdapterResult(
                status="OK", data=scored[:top_k], affected_count=len(scored[:top_k])
            )
        if command.operation == Operation.DELETE:
            vector_id = str(command.validated_payload.get("resource_id") or data.get("id") or "")
            existed = self._vectors.pop((tenant_id, biz_domain, vector_id), None) is not None
            return AdapterResult(
                status="OK", data={"deleted": existed}, affected_count=int(existed)
            )
        raise DataControlError("OPERATION_NOT_SUPPORTED")


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def _as_float(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0
