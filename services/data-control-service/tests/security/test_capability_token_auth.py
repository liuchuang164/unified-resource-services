from datetime import UTC, datetime, timedelta

import jwt
import pytest

from data_control_service.application.context_resolver import ContextResolver
from data_control_service.config.settings import Settings
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.auth.capability_token_auth_provider import (
    CapabilityTokenAuthProvider,
)
from data_control_service.ports.auth_provider import AuthenticationCredential, RequestContext
from tests.integration.test_dispatch_pipeline import base_request

SECRET = "test-capability-secret-with-sufficient-length"  # noqa: S105


def _token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "unified-access-plane",
        "aud": ["data-access-gateway", "data-control-service"],
        "sub": "agent_demo",
        "subject_type": "AGENT",
        "tenant_id": "tenant_demo",
        "biz_domain": "demo",
        "roles": ["AGENT"],
        "permissions": ["data:object:read", "data:object:write"],
        "session_id": "session_demo",
        "task_id": "task_demo",
        "allowed_tools": ["minio_file_access"],
        "allowed_actions": ["minio_file_access:object_exists"],
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "jti_demo",
        **overrides,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _provider() -> CapabilityTokenAuthProvider:
    return CapabilityTokenAuthProvider(
        Settings(
            app_env="test",
            auth_provider="capability_token",
            capability_token_shared_secret=SECRET,
        )
    )


async def test_capability_token_builds_agent_principal() -> None:
    principal = await _provider().authenticate(
        AuthenticationCredential(headers={"authorization": f"Bearer {_token()}"}),
        RequestContext("req_demo", "trace_demo", "DATA_ACCESS_GATEWAY"),
    )
    assert principal.subject_id == "agent_demo"
    assert principal.subject_type == "AGENT"
    assert principal.tenant_id == "tenant_demo"
    assert principal.allowed_biz_domains == ("demo",)
    assert principal.permissions == ("data:object:read", "data:object:write")
    assert principal.session_id == "session_demo"
    assert principal.allowed_actions == ("minio_file_access:object_exists",)


async def test_capability_token_rejects_invalid_audience() -> None:
    with pytest.raises(DataControlError) as exc_info:
        await _provider().authenticate(
            AuthenticationCredential(
                headers={"authorization": f"Bearer {_token(aud=['data-access-gateway'])}"}
            ),
            RequestContext("req_demo", "trace_demo", "DATA_ACCESS_GATEWAY"),
        )
    assert exc_info.value.code == "AUTH_TOKEN_INVALID"


def test_symmetric_capability_token_is_rejected_in_production() -> None:
    with pytest.raises(DataControlError) as exc_info:
        CapabilityTokenAuthProvider(
            Settings(
                app_env="production",
                auth_provider="capability_token",
                capability_token_shared_secret=SECRET,
            )
        )
    assert exc_info.value.code == "CONFIGURATION_INVALID"


async def test_data_control_rechecks_gateway_tool_scope() -> None:
    principal = await _provider().authenticate(
        AuthenticationCredential(headers={"authorization": f"Bearer {_token()}"}),
        RequestContext("req_demo", "trace_demo", "DATA_ACCESS_GATEWAY"),
    )
    body = base_request()
    body["source"] = "DATA_ACCESS_GATEWAY"
    body["auth_context"]["actor"] = {"id": "agent_demo", "type": "AGENT"}
    body["metadata"] = {
        "tool_name": "minio_file_access",
        "tool_action": "delete_object",
        "session_id": "session_demo",
        "task_id": "task_demo",
    }
    with pytest.raises(DataControlError) as exc_info:
        ContextResolver().resolve(
            DataRequest.model_validate(body),
            principal,
            RequestContext("req_demo", "trace_demo", "DATA_ACCESS_GATEWAY"),
        )
    assert exc_info.value.code == "AUTH_SCOPE_MISMATCH"
