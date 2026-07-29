from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from file_media_stream_service.bootstrap import Container, build_container
from file_media_stream_service.main import create_app


@pytest.fixture
def container() -> Container:
    return build_container()


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container))


@pytest.fixture
def service_context() -> Callable[..., dict[str, Any]]:
    def factory(**changes: Any) -> dict[str, Any]:
        context: dict[str, Any] = {
            "request_id": "req-1",
            "trace_id": "trace-1",
            "tenant_id": "dev-tenant",
            "biz_domain": "development",
            "caller_type": "service",
            "caller_id": "dev-service",
            "roles": ["service"],
            "permissions": [],
            "policy_version": "v1",
        }
        context.update(changes)
        return context

    return factory


@pytest.fixture
def agent_context(service_context: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    return service_context(
        caller_type="agent",
        caller_id="dev-agent",
        agent_id="agent-1",
        tool_call_id="tool-call-1",
        capability_token="dev-capability-token",
        nonce="agent-nonce-1",
    )


@pytest.fixture
def upload_payload() -> dict[str, Any]:
    return {
        "filename": "evidence.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 2048,
        "owner_type": "case",
        "owner_id": "case-1",
    }


def operation_request(
    operation: str, context: dict[str, Any], payload: dict[str, Any], api_version: str = "v1"
) -> dict[str, Any]:
    return {
        "api_version": api_version,
        "operation": operation,
        "context": context,
        "payload": payload,
    }
