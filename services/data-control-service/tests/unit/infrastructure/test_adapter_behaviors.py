import pytest
from tests.integration.test_transaction_orchestrator import command
from tests.security.test_adapter_specific_contracts import _with_mapping
from tests.unit.application.test_idempotency_concurrency import context

from data_control_service.adapters.milvus import InMemoryMilvusAdapter
from data_control_service.adapters.minio import InMemoryMinIOAdapter
from data_control_service.adapters.neo4j import InMemoryNeo4jAdapter
from data_control_service.adapters.postgresql import InMemoryPostgreSQLAdapter
from data_control_service.adapters.redis import InMemoryRedisAdapter
from data_control_service.adapters.timescaledb import InMemoryTimescaleDBAdapter
from data_control_service.contracts.enums import Operation
from data_control_service.domain.exceptions import DataControlError


async def test_postgresql_update_list_and_delete() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    await adapter.execute(command(Operation.CREATE, {"id": "doc_a", "title": "a"}), context())
    update = command(Operation.UPDATE, {"id": "doc_a", "title": "b"})
    updated = await adapter.execute(update, context())
    listed = await adapter.execute(command(Operation.LIST, {}), context())
    deleted = await adapter.execute(command(Operation.DELETE, {"id": "doc_a"}), context())
    assert updated.affected_count == 1
    assert listed.data[0]["title"] == "b"
    assert deleted.data["deleted"] is True


async def test_postgresql_rejects_empty_update() -> None:
    adapter = InMemoryPostgreSQLAdapter()
    with pytest.raises(DataControlError):
        await adapter.execute(command(Operation.UPDATE, {}), context())


async def test_minio_create_get_list_and_delete() -> None:
    adapter = InMemoryMinIOAdapter()
    create = _with_mapping(
        command(
            Operation.CREATE,
            {"filename": "a.txt", "content_type": "text/plain", "size_bytes": 1},
        ),
        1,
    )
    created = await adapter.execute(create, context())
    object_id = created.data["object_id"]
    get = _with_mapping(command(Operation.GET, {"object_id": object_id}), 1)
    list_cmd = _with_mapping(command(Operation.LIST, {}), 1)
    delete = _with_mapping(command(Operation.DELETE, {"object_id": object_id}), 1)
    assert (await adapter.execute(get, context())).affected_count == 1
    assert (await adapter.execute(list_cmd, context())).affected_count == 1
    assert (await adapter.execute(delete, context())).data["deleted"] is True


async def test_redis_upsert_get_delete_lock_unlock() -> None:
    adapter = InMemoryRedisAdapter()
    upsert = _with_mapping(
        command(Operation.UPSERT, {"logical_key": "k", "value": "v", "ttl_seconds": 60}),
        2,
    )
    get = _with_mapping(command(Operation.GET, {"logical_key": "k"}), 2)
    lock = _with_mapping(
        command(Operation.LOCK, {"logical_key": "lk", "token": "t", "ttl_seconds": 60}), 2
    )
    unlock = _with_mapping(command(Operation.UNLOCK, {"logical_key": "lk", "token": "t"}), 2)
    delete = _with_mapping(command(Operation.DELETE, {"logical_key": "k"}), 2)
    await adapter.execute(upsert, context())
    assert (await adapter.execute(get, context())).data["value"] == "v"
    assert (await adapter.execute(lock, context())).data["locked"] is True
    assert (await adapter.execute(unlock, context())).data["unlocked"] is True
    assert (await adapter.execute(delete, context())).data["deleted"] is True


async def test_neo4j_create_get_search_relation_delete() -> None:
    adapter = InMemoryNeo4jAdapter()
    first = _with_mapping(command(Operation.CREATE, {"id": "n1", "label": "Entity"}), 3)
    second = _with_mapping(command(Operation.CREATE, {"id": "n2", "label": "Entity"}), 3)
    relation = _with_mapping(
        command(
            Operation.CREATE,
            {"action": "relation", "from_id": "n1", "to_id": "n2", "relation_type": "RELATED_TO"},
        ),
        3,
    )
    get = _with_mapping(command(Operation.GET, {}), 3)
    get = type(get)(
        operation=Operation.GET,
        logical_resource=get.logical_resource,
        validated_payload={**get.validated_payload, "resource_id": "n1"},
        scope=get.scope,
        timeout_ms=get.timeout_ms,
        route_id=get.route_id,
    )
    await adapter.execute(first, context())
    await adapter.execute(second, context())
    assert (await adapter.execute(relation, context())).affected_count == 1
    assert (await adapter.execute(get, context())).data["id"] == "n1"
    assert (
        await adapter.execute(_with_mapping(command(Operation.SEARCH, {}), 3), context())
    ).affected_count == 2
    assert (
        await adapter.execute(_with_mapping(command(Operation.DELETE, {"id": "n1"}), 3), context())
    ).data["deleted"] is True


async def test_milvus_delete_and_invalid_dimension() -> None:
    adapter = InMemoryMilvusAdapter()
    upsert = _with_mapping(command(Operation.UPSERT, {"id": "v1", "vector": [1, 2, 3]}), 4)
    await adapter.execute(upsert, context())
    with pytest.raises(DataControlError):
        await adapter.execute(
            _with_mapping(command(Operation.UPSERT, {"id": "bad", "vector": [1]}), 4), context()
        )
    assert (
        await adapter.execute(_with_mapping(command(Operation.DELETE, {"id": "v1"}), 4), context())
    ).data["deleted"] is True


async def test_timescaledb_create_batch_and_search() -> None:
    adapter = InMemoryTimescaleDBAdapter(max_query_days=10)
    create = _with_mapping(
        command(
            Operation.CREATE,
            {"timestamp": "2026-01-01T00:00:00+00:00", "metric": "m", "value": 1},
        ),
        5,
    )
    batch = _with_mapping(
        command(
            Operation.BATCH,
            {"items": [{"timestamp": "2026-01-02T00:00:00+00:00", "metric": "m", "value": 2}]},
        ),
        5,
    )
    search = _with_mapping(command(Operation.SEARCH, {}), 5)
    search = type(search)(
        operation=Operation.SEARCH,
        logical_resource=search.logical_resource,
        validated_payload={
            **search.validated_payload,
            "query": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-01-03T00:00:00+00:00",
            },
        },
        scope=search.scope,
        timeout_ms=search.timeout_ms,
        route_id=search.route_id,
    )
    await adapter.execute(create, context())
    await adapter.execute(batch, context())
    result = await adapter.execute(search, context())
    assert [item["value"] for item in result.data] == [1.0, 2.0]
