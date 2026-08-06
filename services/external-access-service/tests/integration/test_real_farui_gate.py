import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from external_access_service.bootstrap import build_container
from external_access_service.infrastructure.config import Settings
from external_access_service.main import create_app

DEFAULT_CSV = Path(
    "/Users/liuchuang/Desktop/external-access-server/默认业务空间-apiKey-6381250.csv"
)

OPERATIONS = {
    "legal_consult": "ALI_FARUI_LEGAL_CONSULT",
    "law_search": "ALI_FARUI_LAW_SEARCH",
    "case_search": "ALI_FARUI_CASE_SEARCH",
}


def _credentials_file() -> str | None:
    configured = (
        os.getenv("ALI_FARUI_CREDENTIALS_FILE")
        or os.getenv("FARUI_CREDENTIALS_FILE")
        or os.getenv("EXTERNAL_ACCESS_FARUI_CREDENTIALS_FILE")
    )
    if configured:
        return configured
    if DEFAULT_CSV.exists():
        return str(DEFAULT_CSV)
    return None


def _has_real_farui_config() -> bool:
    if os.getenv("RUN_REAL_FARUI_GATE") != "1":
        return False
    return bool(
        _credentials_file()
        or (
            (
                os.getenv("ALI_FARUI_ACCESS_KEY_ID")
                or os.getenv("FARUI_ACCESS_KEY_ID")
                or os.getenv("ALI_FARUI_APP_KEY")
            )
            and (
                os.getenv("ALI_FARUI_ACCESS_KEY_SECRET")
                or os.getenv("FARUI_ACCESS_KEY_SECRET")
                or os.getenv("ALI_FARUI_APP_SECRET")
            )
            and (os.getenv("ALI_FARUI_WORKSPACE_ID") or os.getenv("FARUI_WORKSPACE_ID"))
        )
    )


@contextmanager
def _real_client() -> Iterator[TestClient]:
    settings = Settings(
        environment="real",
        allow_fake_credentials=False,
        farui_base_url="https://farui.cn-beijing.aliyuncs.com",
        farui_credentials_file=_credentials_file(),
        farui_model=os.getenv("ALI_FARUI_MODEL") or os.getenv("FARUI_MODEL"),
    )
    container = build_container(settings, enable_mock_provider=False)
    with TestClient(create_app(container, settings)) as client:
        yield client


def _dispatch_payload(operation: str, request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "trace_id": f"trace_{request_id}",
        "request_source": "BUSINESS_SERVICE",
        "auth_context": {"tenant_id": "tenant_A", "user_id": "user_001", "roles": ["LAWYER"]},
        "biz_context": {"biz_domain": "LEGAL", "biz_scene": "LEGAL_RESEARCH"},
        "operation": operation,
        "provider": {"provider_code": "ALI_FARUI", "capability": "LEGAL_RESEARCH"},
        "payload": {"query": "民间借贷纠纷中只有转账记录时如何主张还款", "limit": 2},
        "policy": {"timeout_ms": 60000, "retry": {"enabled": False, "max_attempts": 1}},
    }


def _token(client: TestClient, actions: list[str]) -> str:
    return client.app.state.container.capability.issue_for_test(
        {
            "issuer": "hermes",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "allowed_operations": actions,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        }
    )


@pytest.mark.skipif(not _has_real_farui_config(), reason="real Farui config is not available")
def test_real_farui_gate_business_path_three_tools() -> None:
    with _real_client() as client:
        for action, operation in OPERATIONS.items():
            response = client.post(
                "/external/dispatch",
                json=_dispatch_payload(operation, f"real_business_{action}"),
            )
            body = response.json()
            assert response.status_code == 200
            assert body["status"] == "SUCCEEDED", body.get("error")
            assert body["provider"] == "ALI_FARUI"
            assert body["operation"] == operation
            assert body["data"]["summary"] is not None


@pytest.mark.skipif(not _has_real_farui_config(), reason="real Farui config is not available")
def test_real_farui_gate_agent_path_three_tools() -> None:
    with _real_client() as client:
        token = _token(client, list(OPERATIONS))
        for action, operation in OPERATIONS.items():
            response = client.post(
                "/eag/tools/execute",
                json={
                    "request_id": f"real_agent_{action}",
                    "trace_id": f"trace_real_agent_{action}",
                    "agent_id": "agent_001",
                    "tool_call_id": f"tool_call_{action}",
                    "tenant_id": "tenant_A",
                    "biz_domain": "LEGAL",
                    "tool_name": "ali_farui",
                    "action": action,
                    "capability_token": token,
                    "input": {"query": "民间借贷纠纷中只有转账记录时如何主张还款", "limit": 2},
                },
            )
            body = response.json()
            assert response.status_code == 200
            tool_response = body["response"]
            assert tool_response["status"] == "SUCCEEDED", tool_response.get("error")
            assert tool_response["provider"] == "ALI_FARUI"
            assert tool_response["operation"] == operation
            assert tool_response["data"]["summary"] is not None
