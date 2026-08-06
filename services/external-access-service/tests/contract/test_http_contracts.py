from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["status"] == "ready"
    assert ready["providers"]["ALI_FARUI"] == "configured"


def test_external_operations_and_schema(client: TestClient) -> None:
    response = client.get(
        "/external/operations",
        params={"tenant_id": "tenant_A", "biz_domain": "LEGAL"},
    )
    assert response.status_code == 200
    operations = {item["operation"] for item in response.json()["operations"]}
    assert "ALI_FARUI_LEGAL_RESEARCH_FULL" in operations

    schema = client.get("/external/operations/ALI_FARUI_LEGAL_RESEARCH_FULL/schema").json()
    assert schema["schema"]["additionalProperties"] is False


def test_external_dispatch_success(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post("/external/dispatch", json=dispatch_payload())
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "SUCCEEDED"
    assert body["provider"] == "ALI_FARUI"
    assert body["data"]["summary"]
    assert "api_key" not in str(body).lower()


def test_missing_tenant_is_rejected(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    body = dispatch_payload(auth_context={"user_id": "user_001"})
    response = client.post("/external/dispatch", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_operation_fails_closed(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post("/external/dispatch", json=dispatch_payload(operation="UNKNOWN"))
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error"]["code"] == "OPERATION_NOT_FOUND"


def test_scope_conflict_fails_closed(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post(
        "/external/dispatch",
        json=dispatch_payload(payload={"query": "x", "tenant_id": "tenant_B"}),
    )
    assert response.json()["error"]["code"] == "TENANT_SCOPE_MISMATCH"


def test_agent_tools_contracts(client: TestClient) -> None:
    tools = client.get("/eag/tools", params={"tenant_id": "tenant_A", "biz_domain": "LEGAL"}).json()
    assert tools["tools"][0]["tool_name"] == "ali_farui"
    schema = client.get("/eag/tools/ali_farui/schema").json()
    assert "legal_research_full" in schema["actions"]


def test_tool_execute_goes_through_unified_entry(client: TestClient) -> None:
    token = client.app.state.container.capability.issue_for_test(
        {
            "issuer": "hermes",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "allowed_operations": ["legal_research_full"],
            "expires_at": "2026-12-01T00:00:00+00:00",
        }
    )
    response = client.post(
        "/eag/tools/execute",
        json={
            "request_id": "req_tool",
            "trace_id": "trace_tool",
            "agent_id": "agent_001",
            "tool_call_id": "tool_call_001",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "tool_name": "ali_farui",
            "action": "legal_research_full",
            "capability_token": token,
            "input": {"query": "合同解除条件"},
        },
    )
    body = response.json()
    assert body["response"]["status"] == "SUCCEEDED"
    assert body["response"]["operation"] == "ALI_FARUI_LEGAL_RESEARCH_FULL"
    assert body["tool_call_id"] == "tool_call_001"
