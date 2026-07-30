import pytest

from data_control_service.adapters.milvus import InMemoryMilvusAdapter
from data_control_service.adapters.minio import InMemoryMinIOAdapter
from data_control_service.adapters.neo4j import InMemoryNeo4jAdapter
from data_control_service.adapters.redis import InMemoryRedisAdapter
from data_control_service.adapters.timescaledb import InMemoryTimescaleDBAdapter
from data_control_service.contracts.enums import Operation
from data_control_service.domain.exceptions import DataControlError
from tests.integration.test_transaction_orchestrator import command
from tests.unit.application.test_idempotency_concurrency import context


async def test_minio_generates_tenant_prefixed_object_key() -> None:
    adapter = InMemoryMinIOAdapter()
    cmd = command(
        Operation.CREATE,
        {"filename": "a.txt", "content_type": "text/plain", "size_bytes": 1, "content_text": "a"},
    )
    cmd = _with_mapping(cmd, 1)
    result = await adapter.execute(cmd, context())
    assert "object_key" not in result.data
    assert result.data["logical_object_id"].startswith("obj_")


async def test_redis_rejects_raw_command_and_enforces_ttl() -> None:
    adapter = InMemoryRedisAdapter(max_ttl_seconds=10)
    cmd = command(Operation.UPSERT, {"logical_key": "k", "value": "v", "ttl_seconds": 99})
    cmd = _with_mapping(cmd, 2)
    with pytest.raises(DataControlError):
        await adapter.execute(cmd, context())


async def test_neo4j_rejects_unlisted_label() -> None:
    adapter = InMemoryNeo4jAdapter()
    cmd = command(Operation.CREATE, {"id": "n1", "label": "Forbidden"})
    cmd = _with_mapping(cmd, 3)
    with pytest.raises(DataControlError):
        await adapter.execute(cmd, context())


async def test_milvus_computes_scoped_similarity() -> None:
    adapter = InMemoryMilvusAdapter(max_top_k=2)
    upsert = _with_mapping(
        command(
            Operation.UPSERT,
            {"id": "v1", "vector": [1, 0, 0], "metadata": {"source": "test"}},
        ),
        4,
    )
    await adapter.execute(upsert, context())
    search = _with_mapping(command(Operation.SEARCH, {}), 4)
    search = type(search)(
        operation=Operation.SEARCH,
        logical_resource=search.logical_resource,
        validated_payload={
            **search.validated_payload,
            "data": {},
            "query": {"vector": [1, 0, 0], "top_k": 1},
        },
        scope=search.scope,
        timeout_ms=search.timeout_ms,
        route_id=search.route_id,
    )
    result = await adapter.execute(search, context())
    assert result.data[0]["vector_id"] == "v1"
    assert result.data[0]["score"] == 1.0


async def test_timescaledb_requires_bounded_time_range() -> None:
    adapter = InMemoryTimescaleDBAdapter(max_query_days=1)
    search = _with_mapping(command(Operation.SEARCH, {}), 5)
    search = type(search)(
        operation=Operation.SEARCH,
        logical_resource=search.logical_resource,
        validated_payload={
            **search.validated_payload,
            "query": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"},
        },
        scope=search.scope,
        timeout_ms=search.timeout_ms,
        route_id=search.route_id,
    )
    with pytest.raises(DataControlError):
        await adapter.execute(search, context())


def _with_mapping(cmd, index: int):
    from data_control_service.domain.policies import create_default_resource_registry

    mappings = create_default_resource_registry().list_mappings()
    return type(cmd)(
        operation=cmd.operation,
        logical_resource=cmd.logical_resource,
        validated_payload={**cmd.validated_payload, "resource_mapping": mappings[index]},
        scope=cmd.scope,
        timeout_ms=cmd.timeout_ms,
        route_id=cmd.route_id,
    )
