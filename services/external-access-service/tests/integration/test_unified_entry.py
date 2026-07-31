from collections.abc import Callable

import pytest

from external_access_service.domain.models import ExternalDispatchRequest


@pytest.mark.asyncio
async def test_unified_entry_audits_allowed_call(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    response = await container.entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert container.audit.events[-1]["tenant_id"] == "tenant_A"
    assert container.audit.events[-1]["biz_domain"] == "LEGAL"


@pytest.mark.asyncio
async def test_biz_domain_mismatch_is_rejected(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    request = dispatch_request(
        biz_context=dispatch_request().biz_context.model_copy(update={"biz_domain": "FINANCE"})
    )
    response = await container.entry.dispatch(request)
    assert response.error is not None
    assert response.error.code == "BIZ_DOMAIN_SCOPE_MISMATCH"


@pytest.mark.asyncio
async def test_unregistered_provider_is_rejected(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    request = dispatch_request(operation="ALI_FARUI_LEGAL_RESEARCH_FULL")
    container.entry.router._providers = {}
    response = await container.entry.dispatch(request)
    assert response.error is not None
    assert response.error.code == "PROVIDER_NOT_FOUND"


@pytest.mark.asyncio
async def test_payload_unknown_sensitive_fields_rejected(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    response = await container.entry.dispatch(
        dispatch_request(payload={"query": "x", "authorization": "Bearer secret"})
    )
    assert response.error is not None
    assert response.error.code == "INVALID_REQUEST"
    assert "authorization" in str(response.error.details)
