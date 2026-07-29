import asyncio
import logging
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from file_media_stream_service.application.dto import RequestContext, UnifiedRequest
from file_media_stream_service.bootstrap import Container, build_container
from file_media_stream_service.config import Settings


@pytest.mark.asyncio
async def test_concurrent_idempotency_has_one_side_effect(
    container: Container,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    context = RequestContext.model_validate(service_context(idempotency_key="concurrent-upload"))
    requests = [
        UnifiedRequest(
            api_version="v1",
            operation="file.initialize_upload",
            context=context.model_copy(update={"request_id": f"concurrent-{index}"}),
            payload=upload_payload,
        )
        for index in range(8)
    ]
    results = await asyncio.gather(*(container.entry.execute(item) for item in requests))
    assert all(response.success for response in results)
    assert (
        len({response.data["resource"]["resource_id"] for response in results if response.data})
        == 1
    )
    assert len(container.state.files) == 1
    assert len(container.storage.uploads) == 1


def test_public_json_and_logs_do_not_leak_internal_references_or_secrets(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    service_context: Callable[..., dict[str, Any]],
    upload_payload: dict[str, Any],
) -> None:
    caplog.set_level(logging.INFO)
    response = client.post(
        "/api/v1/operations/execute",
        json={
            "api_version": "v1",
            "operation": "file.initialize_upload",
            "context": service_context(idempotency_key="secret-scan"),
            "payload": upload_payload,
        },
    )
    rendered = response.text + caplog.text
    assert "object_key" not in rendered
    assert "endpoint_reference" not in rendered
    assert "X-Amz-Signature" not in rendered
    assert "session_secret" not in rendered
    assert "operation_completed" in caplog.text
    for field in ("request_id", "trace_id", "tenant_id", "biz_domain", "operation"):
        assert field in caplog.text


def test_fake_composition_fails_closed_outside_local_environments() -> None:
    with pytest.raises(RuntimeError, match="Fake adapters"):
        build_container(Settings(environment="production"))
