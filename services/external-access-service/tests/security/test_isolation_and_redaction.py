from collections.abc import Callable

import pytest

from external_access_service.domain.models import ExternalDispatchRequest
from external_access_service.infrastructure.observability.redaction import redact


def test_recursive_redaction() -> None:
    payload = {"headers": {"Authorization": "Bearer secret"}, "nested": {"api_key": "k"}}
    assert redact(payload)["headers"]["Authorization"] == "***REDACTED***"
    assert redact(payload)["nested"]["api_key"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_tenant_a_cannot_use_tenant_b_scope(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    request = dispatch_request(
        auth_context=dispatch_request().auth_context.model_copy(update={"tenant_id": "tenant_B"})
    )
    response = await container.entry.dispatch(request)
    assert response.error is not None
    assert response.error.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_audit_does_not_store_query_or_secrets(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    await container.entry.dispatch(dispatch_request(payload={"query": "secret legal facts"}))
    audit_text = str(container.audit.events[-1])
    assert "secret legal facts" not in audit_text
    assert "test-api-secret" not in audit_text
