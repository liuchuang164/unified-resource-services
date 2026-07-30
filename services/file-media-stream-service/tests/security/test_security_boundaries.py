from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from file_media_stream_service.bootstrap import Container
from file_media_stream_service.security import AuthorizationRule


def unified(operation: str, context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "operation": operation,
        "context": context,
        "payload": payload,
    }


def initialize(
    client: TestClient,
    context: dict[str, Any],
    upload_payload: dict[str, Any],
) -> dict[str, Any]:
    return client.post(
        "/api/v1/operations/execute",
        json=unified("file.initialize_upload", context, upload_payload),
    ).json()


def test_cross_tenant_and_domain_access_are_not_enumerable(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    created = initialize(client, service_context(idempotency_key="u1"), upload_payload)["data"][
        "resource"
    ]
    for scope in (
        {"tenant_id": "other-tenant"},
        {"biz_domain": "other-domain"},
    ):
        response = client.post(
            "/api/v1/operations/execute",
            json=unified(
                "file.get_resource",
                service_context(request_id=f"req-{len(container.audit.events)}", **scope),
                {"resource_id": created["resource_id"]},
            ),
        ).json()
        assert response["success"] is False
        assert response["error"]["code"] == "PERMISSION_DENIED"
    assert len(container.state.files) == 1
    assert [event.decision for event in container.audit.events] == ["ALLOW", "DENY", "DENY"]


def test_missing_tenant_and_caller_are_contract_errors(client: TestClient) -> None:
    for missing in ("tenant_id", "caller_id"):
        context = {
            "request_id": "r",
            "trace_id": "t",
            "tenant_id": "dev-tenant",
            "biz_domain": "development",
            "caller_type": "service",
            "caller_id": "dev-service",
        }
        context.pop(missing)
        response = client.post(
            "/api/v1/operations/execute",
            json=unified("file.get_resource", context, {"resource_id": "x"}),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unauthorized_operation_denied_and_audited(
    client: TestClient, container: Container, service_context: Callable[..., dict[str, Any]]
) -> None:
    response = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "file.get_resource",
            service_context(caller_id="unknown-service"),
            {"resource_id": "res-x"},
        ),
    ).json()
    assert response["error"]["code"] == "PERMISSION_DENIED"
    assert container.audit.events[-1].decision == "DENY"
    assert container.audit.events[-1].error_code == "PERMISSION_DENIED"


def test_stream_operation_maps_to_required_actions(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    allowed = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.create_stream_session",
            service_context(idempotency_key="stream-action-allow"),
            {"protocol": "WEBRTC", "direction": "INGRESS"},
        ),
    ).json()
    assert allowed["success"] is True

    container.security.rules = (
        AuthorizationRule(
            "dev-service",
            "dev-tenant",
            "development",
            "media_stream:create",
            allowed=True,
        ),
    )
    missing_action = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.create_stream_session",
            service_context(
                request_id="stream-action-missing",
                idempotency_key="stream-action-missing",
            ),
            {"protocol": "WEBRTC", "direction": "INGRESS"},
        ),
    ).json()
    assert missing_action["error"]["code"] == "PERMISSION_DENIED"

    denied_operation = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.close_stream_session",
            service_context(request_id="stream-close-denied"),
            {"session_id": "missing"},
        ),
    ).json()
    assert denied_operation["error"]["code"] == "PERMISSION_DENIED"

    container.security.rules = (
        AuthorizationRule(
            "dev-service",
            "other-tenant",
            "development",
            "media_stream:close",
            allowed=True,
        ),
    )
    tenant_mismatch = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.close_stream_session",
            service_context(request_id="stream-tenant-mismatch"),
            {"session_id": "missing"},
        ),
    ).json()
    assert tenant_mismatch["error"]["code"] == "PERMISSION_DENIED"


def test_agent_requires_valid_capability_token(
    client: TestClient, agent_context: dict[str, Any]
) -> None:
    context = {**agent_context, "capability_token": "invalid"}
    response = client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "file.get_resource",
            "context": context,
            "params": {"resource_id": "x"},
        },
    ).json()
    assert response["response"]["error"]["code"] == "UNAUTHENTICATED"


def test_agent_cannot_bypass_gateway(client: TestClient, agent_context: dict[str, Any]) -> None:
    response = client.post(
        "/api/v1/operations/execute",
        json=unified("file.get_resource", agent_context, {"resource_id": "x"}),
    ).json()
    assert response["error"]["code"] == "PERMISSION_DENIED"


def test_agent_nonce_is_mandatory(client: TestClient, agent_context: dict[str, Any]) -> None:
    context = {key: value for key, value in agent_context.items() if key != "nonce"}
    response = client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "file.get_resource",
            "context": context,
            "params": {"resource_id": "x"},
        },
    ).json()
    assert response["response"]["error"]["code"] == "REPLAY_DETECTED"


def test_duplicate_nonce_is_rejected(
    client: TestClient,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    context = service_context(nonce="nonce-1")
    first = client.post(
        "/api/v1/operations/execute",
        json=unified("file.get_resource", context, {"resource_id": "missing"}),
    ).json()
    second = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "file.get_resource",
            {**context, "request_id": "req-2"},
            {"resource_id": "missing"},
        ),
    ).json()
    assert first["error"]["code"] == "FILE_RESOURCE_NOT_FOUND"
    assert second["error"]["code"] == "REPLAY_DETECTED"


def test_idempotency_same_request_has_one_side_effect_and_conflict_on_change(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    context = service_context(idempotency_key="same-key")
    first = initialize(client, context, upload_payload)
    second = initialize(client, {**context, "request_id": "req-2"}, upload_payload)
    assert first["data"] == second["data"]
    assert len(container.state.files) == 1


def test_idempotent_retry_does_not_consume_quota_twice(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    key = ("dev-tenant", "development", "file.initialize_upload")
    container.security.quotas[key] = 1
    context = service_context(idempotency_key="quota-idempotency")
    first = initialize(client, context, upload_payload)
    second = initialize(client, {**context, "request_id": "quota-retry"}, upload_payload)
    assert first["data"] == second["data"]
    assert container.security.quotas[key] == 0
    assert len(container.storage.uploads) == 1

    conflict = initialize(
        client,
        {**context, "request_id": "req-3"},
        {**upload_payload, "size_bytes": 999},
    )
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(container.state.files) == 1


def test_client_physical_paths_are_rejected(
    client: TestClient,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    for field in ("bucket", "object_key", "physical_path", "disk_path", "media_internal_path"):
        response = initialize(
            client,
            service_context(request_id=f"r-{field}", idempotency_key=f"i-{field}"),
            {**upload_payload, field: "client-controlled"},
        )
        assert response["error"]["code"] == "INVALID_REQUEST"


def test_missing_stream_job_and_input_have_scoped_error_codes(
    client: TestClient,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    cases = (
        ("media.get_stream_session", {"session_id": "missing"}, "STREAM_SESSION_NOT_FOUND"),
        (
            "media.close_stream_session",
            {"session_id": "missing"},
            "STREAM_SESSION_NOT_FOUND",
        ),
        ("media.get_processing_job", {"job_id": "missing"}, "PROCESSING_JOB_NOT_FOUND"),
        (
            "media.submit_processing_job",
            {
                "operation": "OCR",
                "input_resource_id": "missing",
                "processor_type": "fake",
            },
            "FILE_RESOURCE_NOT_FOUND",
        ),
    )
    for index, (operation, payload, code) in enumerate(cases):
        context = service_context(request_id=f"missing-{index}")
        if operation in {"media.close_stream_session", "media.submit_processing_job"}:
            context["idempotency_key"] = f"missing-{index}"
        response = client.post(
            "/api/v1/operations/execute",
            json=unified(operation, context, payload),
        ).json()
        assert response["error"]["code"] == code


def test_quota_denial_occurs_before_use_case(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    container.security.quotas[("dev-tenant", "development", "file.get_resource")] = 0
    response = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "file.get_resource",
            service_context(),
            {"resource_id": "missing"},
        ),
    ).json()
    assert response["error"]["code"] == "QUOTA_EXCEEDED"
    assert container.audit.events[-1].decision == "DENY"


def test_quota_is_consumed(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    container.security.quotas[("dev-tenant", "development", "file.get_resource")] = 1
    first = client.post(
        "/api/v1/operations/execute",
        json=unified("file.get_resource", service_context(), {"resource_id": "missing"}),
    ).json()
    second = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "file.get_resource",
            service_context(request_id="quota-2"),
            {"resource_id": "missing"},
        ),
    ).json()
    assert first["error"]["code"] == "FILE_RESOURCE_NOT_FOUND"
    assert second["error"]["code"] == "QUOTA_EXCEEDED"
