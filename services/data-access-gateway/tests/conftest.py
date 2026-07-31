from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from data_access_gateway.app import create_app
from data_access_gateway.auth import CapabilityTokenVerifier
from data_access_gateway.client import DownstreamResponse
from data_access_gateway.config import Settings
from data_access_gateway.dependencies import get_tool_execution_service, get_verifier
from data_access_gateway.minio_tool import MINIO_TOOL
from data_access_gateway.registry import ToolRegistry
from data_access_gateway.service import ToolExecutionService

SECRET = "test-capability-secret-with-sufficient-length"  # noqa: S105


class FakeDataControlClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response = DownstreamResponse(
            200,
            {
                "success": True,
                "code": "OK",
                "trace_id": "trace_demo_001",
                "data": {"logical_object_id": "obj_demo", "exists": True},
                "meta": {"idempotency_replayed": False},
            },
        )

    async def dispatch(
        self,
        request: dict[str, Any],
        capability_token: str,
    ) -> DownstreamResponse:
        assert capability_token
        self.requests.append(request)
        return self.response

    async def ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "unified-access-plane",
            "aud": ["data-access-gateway", "data-control-service"],
            "sub": "agent_demo",
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "session_id": "session_demo",
            "task_id": "task_demo",
            "roles": ["AGENT"],
            "permissions": [
                "data:object:read",
                "data:object:write",
                "data:high-risk:execute",
            ],
            "allowed_tools": ["minio_file_access"],
            "allowed_actions": [
                f"minio_file_access:{action.name}" for action in MINIO_TOOL.actions
            ],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "jti_demo",
        },
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def fake_client() -> FakeDataControlClient:
    return FakeDataControlClient()


@pytest.fixture
async def client(
    fake_client: FakeDataControlClient,
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    settings = Settings(
        app_env="test",
        capability_token_shared_secret=SECRET,
    )
    app.dependency_overrides[get_verifier] = lambda: CapabilityTokenVerifier(settings)
    app.dependency_overrides[get_tool_execution_service] = lambda: ToolExecutionService(
        ToolRegistry([MINIO_TOOL]),
        fake_client,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as async_client:
        yield async_client


@pytest.fixture
def base_request() -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "request_id": "req_demo_001",
        "trace_id": "trace_demo_001",
        "session_id": "session_demo",
        "task_id": "task_demo",
        "tool_call_id": "call_demo_001",
        "tenant_id": "tenant_demo",
        "biz_domain": "demo",
        "tool_name": "minio_file_access",
        "action": "object_exists",
        "params": {"logical_object_id": "obj_demo"},
        "timeout_ms": 10000,
    }
