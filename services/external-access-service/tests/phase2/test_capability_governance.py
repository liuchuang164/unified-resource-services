from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _token(client: TestClient, **changes: object) -> str:
    claims: dict[str, object] = {
        "issuer": "hermes",
        "tenant_id": "tenant_A",
        "biz_domain": "LEGAL",
        "allowed_operations": ["legal_research_full"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    claims.update(changes)
    return client.app.state.container.capability.issue_for_test(claims)


def _tool_payload(token: str) -> dict[str, object]:
    return {
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
    }


def test_valid_capability_token_allows_tool_execution(client: TestClient) -> None:
    response = client.post("/eag/tools/execute", json=_tool_payload(_token(client)))
    assert response.json()["response"]["status"] == "SUCCEEDED"


def test_expired_capability_token_rejected(client: TestClient) -> None:
    token = _token(client, expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    response = client.post("/eag/tools/execute", json=_tool_payload(token))
    assert response.json()["error"]["code"] == "CAPABILITY_EXPIRED"


def test_invalid_signature_rejected(client: TestClient) -> None:
    token = _token(client).replace("a", "b", 1)
    response = client.post("/eag/tools/execute", json=_tool_payload(token))
    assert response.json()["error"]["code"] in {"CAPABILITY_INVALID", "INVALID_REQUEST"}


def test_operation_scope_denied(client: TestClient) -> None:
    response = client.post(
        "/eag/tools/execute",
        json=_tool_payload(_token(client, allowed_operations=["law_search"])),
    )
    assert response.json()["error"]["code"] == "CAPABILITY_SCOPE_DENIED"


def test_tenant_scope_denied(client: TestClient) -> None:
    response = client.post(
        "/eag/tools/execute",
        json=_tool_payload(_token(client, tenant_id="tenant_B")),
    )
    assert response.json()["error"]["code"] == "CAPABILITY_SCOPE_DENIED"
