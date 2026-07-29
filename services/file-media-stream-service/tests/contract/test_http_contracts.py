from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def request(
    operation: str, context: dict[str, Any], payload: dict[str, Any], version: str = "v1"
) -> dict[str, Any]:
    return {
        "api_version": version,
        "operation": operation,
        "context": context,
        "payload": payload,
    }


def test_health_ready_and_openapi(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/operations/execute" in paths
    assert "/api/v1/tools/execute" in paths


def test_tools_and_schema_contract(client: TestClient) -> None:
    tools = client.get("/api/v1/tools").json()["tools"]
    assert {item["name"] for item in tools} >= {
        "file_media.list_tools",
        "file_media.get_tool_schema",
        "file.initialize_upload",
        "media.create_stream_session",
    }
    schema_response = client.get("/api/v1/tools/file.initialize_upload/schema")
    assert schema_response.status_code == 200
    schema = schema_response.json()["schema"]
    assert set(schema["required"]) == {
        "filename",
        "mime_type",
        "size_bytes",
        "owner_type",
        "owner_id",
    }
    assert schema["properties"]["filename"]["maxLength"] == 255
    assert schema["properties"]["size_bytes"]["maximum"] == 10 * 1024 * 1024 * 1024


def test_missing_tool_schema_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/tools/unknown/schema")
    assert response.status_code == 404


def test_unsupported_api_version_has_stable_error(
    client: TestClient,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    response = client.post(
        "/api/v1/operations/execute",
        json=request(
            "file.get_resource",
            service_context(),
            {"resource_id": "missing"},
            version="v99",
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"] == {
        "code": "UNSUPPORTED_API_VERSION",
        "message": "API version is not supported",
        "retryable": False,
        "details": {},
    }


def test_unsupported_operation_has_stable_error(
    client: TestClient,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    response = client.post(
        "/api/v1/operations/execute",
        json=request("unknown.operation", service_context(), {}),
    )
    assert response.json()["error"]["code"] == "UNSUPPORTED_OPERATION"


def test_framework_validation_uses_unified_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.get_resource",
            "context": {"request_id": "r", "trace_id": "t"},
            "payload": {},
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert "traceback" not in str(body).lower()
