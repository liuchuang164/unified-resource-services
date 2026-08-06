from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_business_and_agent_paths_share_unified_response(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    token = client.app.state.container.capability.issue_for_test(
        {
            "issuer": "hermes",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "allowed_operations": ["legal_research_full"],
            "expires_at": "2026-12-01T00:00:00+00:00",
        }
    )
    business = client.post("/external/dispatch", json=dispatch_payload()).json()
    agent = client.post(
        "/eag/tools/execute",
        json={
            "request_id": "req_agent",
            "trace_id": "trace_agent",
            "agent_id": "agent_001",
            "tool_call_id": "tool_call_001",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "tool_name": "ali_farui",
            "action": "legal_research_full",
            "capability_token": token,
            "input": {"query": "法律研究"},
        },
    ).json()["response"]
    assert business["operation"] == agent["operation"] == "ALI_FARUI_LEGAL_RESEARCH_FULL"
    assert business["provider"] == agent["provider"] == "ALI_FARUI"
