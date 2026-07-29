from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from file_media_stream_service.bootstrap import Container


async def unavailable_upload(object_key: str, mime_type: str, size_bytes: int) -> str:
    raise RuntimeError("SDK secret: Bearer secret-token")


async def unavailable_processor(
    processor_type: str, input_resource_id: str, options: dict[str, Any]
) -> None:
    raise RuntimeError("processor unavailable")


async def unavailable_event(event_name: str, payload: dict[str, Any]) -> None:
    raise RuntimeError("event bus unavailable")


async def unavailable_save(session: Any) -> None:
    raise RuntimeError("metadata store unavailable")


async def unavailable_delete(tenant_id: str, biz_domain: str, resource_id: str) -> None:
    raise RuntimeError("metadata compensation unavailable")


async def unavailable_abort(object_key: str) -> None:
    raise RuntimeError("storage compensation unavailable")


async def unavailable_audit(event: Any) -> None:
    raise RuntimeError("audit sink unavailable")


def test_adapter_exception_is_mapped_and_audited_without_sdk_details(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    container.storage.initialize_upload = unavailable_upload
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.initialize_upload",
            "context": service_context(idempotency_key="failure"),
            "payload": upload_payload,
        },
    ).json()
    rendered = str(response)
    assert response["error"]["code"] == "INTERNAL_ERROR"
    assert "Bearer secret-token" not in rendered
    assert container.audit.events[-1].result == "FAILURE"
    assert container.state.files == {}


def test_processor_failure_marks_job_failed(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    created = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.initialize_upload",
            "context": service_context(idempotency_key="upload-before-job"),
            "payload": upload_payload,
        },
    ).json()["data"]["resource"]
    container.processor.submit = unavailable_processor
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "media.submit_processing_job",
            "context": service_context(request_id="job-fail", idempotency_key="job-fail"),
            "payload": {
                "operation": "OCR",
                "input_resource_id": created["resource_id"],
                "processor_type": "fake",
            },
        },
    ).json()
    assert response["error"]["code"] == "INTERNAL_ERROR"
    job = next(iter(container.state.jobs.values()))
    assert job.status.value == "FAILED"


def test_event_failure_compensates_resource_and_upload(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    container.events.publish = unavailable_event
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.initialize_upload",
            "context": service_context(idempotency_key="event-fail"),
            "payload": upload_payload,
        },
    ).json()
    assert response["error"]["code"] == "INTERNAL_ERROR"
    assert container.state.files == {}
    assert container.storage.uploads == {}


def test_close_save_failure_emits_reconciliation_event(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    created = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "media.create_stream_session",
            "context": service_context(idempotency_key="create-for-save-fail"),
            "payload": {"protocol": "WEBRTC", "direction": "INGRESS"},
        },
    ).json()["data"]["session"]
    container.entry.use_cases.sessions.save = unavailable_save
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "media.close_stream_session",
            "context": service_context(request_id="close-fail", idempotency_key="close-fail"),
            "payload": {"session_id": created["session_id"]},
        },
    ).json()
    assert response["error"]["code"] == "INTERNAL_ERROR"
    assert container.events.events[-1] == (
        "media.session_reconciliation_required",
        {"session_id": created["session_id"]},
    )
    stored = next(iter(container.state.sessions.values()))
    assert stored.status.value == "READY"
    assert f"session-close:{created['session_id']}" in container.reconciliation.pending


def test_double_compensation_failure_leaves_pending_reconciliation(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    container.events.publish = unavailable_event
    container.entry.use_cases.files.delete = unavailable_delete
    container.storage.abort_upload = unavailable_abort
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.initialize_upload",
            "context": service_context(idempotency_key="double-fail"),
            "payload": upload_payload,
        },
    ).json()
    assert response["error"]["code"] == "INTERNAL_ERROR"
    pending = next(iter(container.reconciliation.pending.values()))
    assert pending[0] == "UPLOAD_COMPENSATION"
    assert pending[1]["tenant_id"] == "dev-tenant"


def test_audit_sink_failure_does_not_escape_unified_response(
    client: TestClient,
    container: Container,
    service_context: Callable[..., dict[str, Any]],
) -> None:
    container.audit.write = unavailable_audit
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.get_resource",
            "context": service_context(),
            "payload": {"resource_id": "missing"},
        },
    ).json()
    assert response["error"]["code"] == "FILE_RESOURCE_NOT_FOUND"
