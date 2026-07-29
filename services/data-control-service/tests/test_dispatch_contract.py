from typing import Any

from httpx import AsyncClient


def base_request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "contract_version": "1.0",
        "request_id": "req_01J_TEST",
        "trace_id": "trace_01J_TEST",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "subject_id": "svc_case",
            "subject_type": "SERVICE",
            "tenant_id": "tenant_001",
            "biz_domain": "litigation",
            "roles": [],
            "permissions": ["data:case:read", "data:case:write"],
        },
        "operation": "CREATE",
        "resource": {
            "target": "POSTGRESQL",
            "type": "CASE_RECORD",
            "name": "case",
            "resource_id": "case_001",
        },
        "payload": {"data": {"id": "case_001", "title": "case"}, "query": {}, "options": {}},
        "idempotency_key": "idem_01J_TEST",
        "transaction": {"mode": "LOCAL", "isolation": "READ_COMMITTED"},
        "timeout_ms": 5000,
        "metadata": {"caller_service": "ontology-service"},
    }
    request.update(overrides)
    return request


async def test_dispatch_create_success(client: AsyncClient) -> None:
    response = await client.post("/data/dispatch", json=base_request())
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["code"] == "OK"
    assert body["meta"]["adapter"] == "postgresql"
    assert body["data"]["resource_id"] == "case_001"


async def test_write_requires_idempotency_key(client: AsyncClient) -> None:
    request = base_request()
    request.pop("idempotency_key")
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] in {"IDEMPOTENCY_KEY_REQUIRED", "REQUEST_SCHEMA_INVALID"}


async def test_unknown_resource_is_rejected_closed(client: AsyncClient) -> None:
    request = base_request(
        resource={"target": "POSTGRESQL", "type": "CASE_RECORD", "name": "raw_table"}
    )
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 422
    assert response.json()["code"] == "RESOURCE_TYPE_UNKNOWN"


async def test_raw_sql_payload_is_rejected(client: AsyncClient) -> None:
    request = base_request(
        payload={"data": {}, "query": {"raw_sql": "select * from users"}, "options": {}}
    )
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_permission_denied_for_write(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["permissions"] = ["data:case:read"]
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_scope_mismatch_for_biz_domain(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["biz_domain"] = "finance"
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_idempotency_replay_and_conflict(client: AsyncClient) -> None:
    first = await client.post("/data/dispatch", json=base_request())
    second = await client.post("/data/dispatch", json=base_request())
    changed = base_request(
        payload={"data": {"id": "case_001", "title": "changed"}, "query": {}, "options": {}}
    )
    conflict = await client.post("/data/dispatch", json=changed)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["meta"]["idempotency_replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"
