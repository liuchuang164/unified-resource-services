from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from data_control_service.api.dependencies import get_auth_provider, get_data_control_service
from data_control_service.app import create_app as create_data_control_app
from data_control_service.config.settings import Settings as DataControlSettings
from data_control_service.infrastructure.auth.capability_token_auth_provider import (
    CapabilityTokenAuthProvider,
)
from httpx import ASGITransport, AsyncClient

from data_access_gateway.auth import CapabilityTokenVerifier
from data_access_gateway.client import DownstreamResponse
from data_access_gateway.config import Settings as GatewaySettings
from data_access_gateway.contracts import ToolExecuteRequest
from data_access_gateway.minio_tool import MINIO_TOOL
from data_access_gateway.registry import ToolRegistry
from data_access_gateway.service import ToolExecutionService

SECRET = "test-full-chain-capability-secret"  # noqa: S105


class ASGIDataControlClient:
    def __init__(self) -> None:
        app = create_data_control_app()
        app.dependency_overrides[get_auth_provider] = lambda: CapabilityTokenAuthProvider(
            DataControlSettings(
                app_env="test",
                auth_provider="capability_token",
                capability_token_shared_secret=SECRET,
            )
        )
        self._client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://data-control",
        )

    async def dispatch(
        self,
        request: dict[str, Any],
        capability_token: str,
    ) -> DownstreamResponse:
        response = await self._client.post(
            "/data/dispatch",
            json=request,
            headers={
                "Authorization": f"Bearer {capability_token}",
                "X-Request-Id": str(request["request_id"]),
                "X-Trace-Id": str(request["trace_id"]),
            },
        )
        return DownstreamResponse(response.status_code, response.json())

    async def ready(self) -> bool:
        return True

    async def close(self) -> None:
        await self._client.aclose()


def _token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "unified-access-plane",
            "aud": ["data-access-gateway", "data-control-service"],
            "sub": "agent_demo",
            "subject_type": "AGENT",
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
            "jti": "jti_full_chain",
        },
        SECRET,
        algorithm="HS256",
    )


async def test_agent_tool_reaches_data_control_minio_adapter_and_replays_idempotently() -> None:
    get_data_control_service.cache_clear()
    client = ASGIDataControlClient()
    try:
        service = ToolExecutionService(ToolRegistry([MINIO_TOOL]), client)
        verifier = CapabilityTokenVerifier(
            GatewaySettings(app_env="test", capability_token_shared_secret=SECRET)
        )
        token, principal = verifier.verify_authorization(f"Bearer {_token()}")
        request = ToolExecuteRequest.model_validate(
            {
                "contract_version": "1.0",
                "request_id": "req_full_chain_001",
                "trace_id": "trace_full_chain_001",
                "session_id": "session_demo",
                "task_id": "task_demo",
                "tool_call_id": "call_full_chain_001",
                "tenant_id": "tenant_demo",
                "biz_domain": "demo",
                "tool_name": "minio_file_access",
                "action": "upload_inline",
                "params": {
                    "logical_object_id": "obj_full_chain",
                    "filename": "full-chain.txt",
                    "content_type": "text/plain",
                    "size_bytes": 16,
                    "content_text": "hello full chain",
                },
                "timeout_ms": 10000,
            }
        )
        first_status, first = await service.execute(request, principal, token)
        replay_request = request.model_copy(
            update={
                "request_id": "req_full_chain_002",
                "trace_id": "trace_full_chain_002",
            }
        )
        replay_status, replay = await service.execute(replay_request, principal, token)
    finally:
        await client.close()
        get_data_control_service.cache_clear()

    assert first_status == 200
    assert first.success is True
    assert replay_status == 200
    assert replay.success is True
    assert replay.meta["idempotency_replayed"] is True
