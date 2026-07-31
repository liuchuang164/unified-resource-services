from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_business_and_agent_paths_share_unified_response(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
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
            "capability_token": "cap_test",
            "input": {"query": "法律研究"},
        },
    ).json()["response"]
    assert business["operation"] == agent["operation"] == "ALI_FARUI_LEGAL_RESEARCH_FULL"
    assert business["provider"] == agent["provider"] == "ALI_FARUI"
