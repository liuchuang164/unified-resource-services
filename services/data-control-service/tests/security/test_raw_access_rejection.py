from httpx import AsyncClient

from tests.integration.test_dispatch_pipeline import base_request


async def test_raw_cypher_payload_is_rejected(client: AsyncClient) -> None:
    request = base_request(
        operation="CREATE",
        resource={"target": "NEO4J", "type": "GRAPH_ENTITY", "name": "entity"},
        payload={"data": {"raw_cypher": "MATCH (n) RETURN n"}, "query": {}, "options": {}},
        idempotency_key="idem_graph_raw",
    )
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_redis_raw_command_payload_is_rejected(client: AsyncClient) -> None:
    request = base_request(
        operation="UPSERT",
        resource={"target": "REDIS", "type": "CACHE_ENTRY", "name": "cache"},
        payload={"data": {"raw_command": "FLUSHALL"}, "query": {}, "options": {}},
        idempotency_key="idem_redis_raw",
    )
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"
