from typing import Any

from httpx import ASGITransport, AsyncClient

from data_control_service.app import create_app, redact


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


async def post(request: dict[str, Any]) -> Any:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/data/dispatch", json=request)


async def test_dispatch_create_success() -> None:
    response = await post(base_request())
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["code"] == "OK"
    assert body["meta"]["adapter"] == "postgresql"
    assert body["data"]["resource_id"] == "case_001"


async def test_write_requires_idempotency_key() -> None:
    request = base_request()
    request.pop("idempotency_key")
    response = await post(request)
    assert response.status_code == 400
    assert response.json()["code"] in {"IDEMPOTENCY_KEY_REQUIRED", "REQUEST_SCHEMA_INVALID"}


async def test_unknown_resource_is_rejected_closed() -> None:
    request = base_request(resource={"target": "POSTGRESQL", "type": "CASE_RECORD", "name": "raw_table"})
    response = await post(request)
    assert response.status_code == 422
    assert response.json()["code"] == "RESOURCE_TYPE_UNKNOWN"


async def test_raw_sql_payload_is_rejected() -> None:
    request = base_request(payload={"data": {}, "query": {"raw_sql": "select * from users"}, "options": {}})
    response = await post(request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_permission_denied_for_write() -> None:
    request = base_request()
    request["auth_context"]["permissions"] = ["data:case:read"]
    response = await post(request)
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_scope_mismatch_for_biz_domain() -> None:
    request = base_request()
    request["auth_context"]["biz_domain"] = "finance"
    response = await post(request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_idempotency_replay_and_conflict_in_same_app() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/data/dispatch", json=base_request())
        second = await client.post("/data/dispatch", json=base_request())
        changed = base_request(payload={"data": {"id": "case_001", "title": "changed"}, "query": {}, "options": {}})
        conflict = await client.post("/data/dispatch", json=changed)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["meta"]["idempotency_replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_redact_recursively_removes_secret_values() -> None:
    value = {"Authorization": "Bearer test", "nested": {"password": "test-password"}, "items": [{"token": "test-token"}]}
    assert redact(value) == {"Authorization": "***REDACTED***", "nested": {"password": "***REDACTED***"}, "items": [{"token": "***REDACTED***"}]}
