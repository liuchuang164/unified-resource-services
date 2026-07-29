from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from file_media_stream_service.bootstrap import Container


def unified(operation: str, context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "operation": operation,
        "context": context,
        "payload": payload,
    }


def test_business_service_full_file_and_job_loop(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    initialize_context = service_context(idempotency_key="upload-1")
    initialized = client.post(
        "/api/v1/operations/execute",
        json=unified("file.initialize_upload", initialize_context, upload_payload),
    ).json()
    assert initialized["success"] is True
    resource = initialized["data"]["resource"]
    assert resource["tenant_id"] == "dev-tenant"
    assert resource["biz_domain"] == "development"
    assert resource["status"] == "PENDING_UPLOAD"
    stored = next(iter(container.state.files.values()))
    assert stored.object_key in container.storage.uploads
    assert "object_key" not in resource

    fetched = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "file.get_resource",
            service_context(request_id="req-2"),
            {"resource_id": resource["resource_id"]},
        ),
    ).json()
    assert fetched["data"]["resource"] == resource

    submitted = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.submit_processing_job",
            service_context(request_id="req-3", idempotency_key="job-1"),
            {
                "operation": "OCR",
                "input_resource_id": resource["resource_id"],
                "processor_type": "fake-ocr",
                "options": {"language": "zh"},
            },
        ),
    ).json()
    assert submitted["data"]["job"]["status"] == "QUEUED"
    assert container.processor.submissions == [
        ("fake-ocr", resource["resource_id"], {"language": "zh"})
    ]
    job_id = submitted["data"]["job"]["job_id"]
    fetched_job = client.post(
        "/api/v1/operations/execute",
        json=unified(
            "media.get_processing_job",
            service_context(request_id="req-4"),
            {"job_id": job_id},
        ),
    ).json()
    assert fetched_job["data"]["job"]["job_id"] == job_id
    assert len(container.audit.events) == 4
    assert all(event.decision == "ALLOW" for event in container.audit.events)


def test_agent_gateway_stream_session_loop(
    client: TestClient,
    container: Container,
    agent_context: dict[str, Any],
) -> None:
    create = client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "media.create_stream_session",
            "context": {**agent_context, "idempotency_key": "session-1"},
            "params": {"protocol": "WEBRTC", "direction": "BIDIRECTIONAL"},
        },
    )
    assert create.status_code == 200
    wrapper = create.json()
    assert wrapper["tool_call_id"] == "tool-call-1"
    session = wrapper["response"]["data"]["session"]
    assert session["status"] == "READY"
    stored = next(iter(container.state.sessions.values()))
    assert container.media_server.sessions[stored.endpoint_reference] is True
    assert "endpoint_reference" not in session

    fetched = client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "media.get_stream_session",
            "context": {
                **agent_context,
                "request_id": "req-agent-2",
                "nonce": "agent-nonce-2",
            },
            "params": {"session_id": session["session_id"]},
        },
    ).json()
    assert fetched["response"]["data"]["session"]["session_id"] == session["session_id"]

    closed = client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "media.close_stream_session",
            "context": {
                **agent_context,
                "request_id": "req-agent-3",
                "idempotency_key": "close-1",
                "nonce": "agent-nonce-3",
            },
            "params": {"session_id": session["session_id"]},
        },
    ).json()
    assert closed["response"]["data"]["session"]["status"] == "CLOSED"
    assert container.media_server.sessions[stored.endpoint_reference] is False
    assert [event.operation for event in container.audit.events] == [
        "media.create_stream_session",
        "media.get_stream_session",
        "media.close_stream_session",
    ]
