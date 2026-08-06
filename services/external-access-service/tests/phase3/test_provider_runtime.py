from collections.abc import Callable

import httpx
import pytest
from conftest import container_with_transport
from fastapi.testclient import TestClient

from external_access_service.application.provider_runtime import (
    ExternalProvider,
    ProviderLifecycleManager,
    ProviderRegistry,
    ProviderRoute,
    ProviderRoutingEngine,
    ProviderRuntimeStatus,
)
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


def test_provider_registry_register_query_and_disable() -> None:
    registry = ProviderRegistry()
    registry.register(
        ExternalProvider(
            provider_code=ProviderCode.MOCK_LEGAL_PROVIDER,
            name="Mock",
            status=ProviderRuntimeStatus.ENABLED,
            supported_operations=("ALI_FARUI_LEGAL_RESEARCH_FULL",),
        )
    )
    assert registry.get(ProviderCode.MOCK_LEGAL_PROVIDER).name == "Mock"
    lifecycle = ProviderLifecycleManager(registry)
    disabled = lifecycle.disable_provider(ProviderCode.MOCK_LEGAL_PROVIDER)
    assert disabled.status == ProviderRuntimeStatus.DISABLED


def test_provider_lifecycle_enable_degraded_unavailable() -> None:
    registry = ProviderRegistry(
        (
            ExternalProvider(
                provider_code=ProviderCode.ALI_FARUI,
                name="Farui",
                supported_operations=("ALI_FARUI_LEGAL_RESEARCH_FULL",),
            ),
        )
    )
    lifecycle = ProviderLifecycleManager(registry)
    assert lifecycle.enable_provider(ProviderCode.ALI_FARUI).status == ProviderRuntimeStatus.ENABLED
    assert lifecycle.mark_degraded(ProviderCode.ALI_FARUI).status == ProviderRuntimeStatus.DEGRADED
    assert (
        lifecycle.mark_unavailable(ProviderCode.ALI_FARUI).status
        == ProviderRuntimeStatus.UNAVAILABLE
    )


def test_provider_routing_priority_and_unavailable_fallback(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    registry = ProviderRegistry(
        (
            ExternalProvider(
                provider_code=ProviderCode.ALI_FARUI,
                name="Farui",
                status=ProviderRuntimeStatus.UNAVAILABLE,
                supported_operations=("ALI_FARUI_LEGAL_RESEARCH_FULL",),
            ),
            ExternalProvider(
                provider_code=ProviderCode.MOCK_LEGAL_PROVIDER,
                name="Mock",
                status=ProviderRuntimeStatus.ENABLED,
                supported_operations=("ALI_FARUI_LEGAL_RESEARCH_FULL",),
            ),
        )
    )
    router = ProviderRoutingEngine(
        registry,
        (
            ProviderRoute(ProviderCode.ALI_FARUI, 10),
            ProviderRoute(ProviderCode.MOCK_LEGAL_PROVIDER, 20),
        ),
    )
    assert router.candidates(dispatch_request()) == [ProviderCode.MOCK_LEGAL_PROVIDER]


def test_provider_apis(client: TestClient) -> None:
    providers = client.get("/external/providers").json()["providers"]
    codes = {provider["provider_code"] for provider in providers}
    assert {"ALI_FARUI", "MOCK_LEGAL_PROVIDER"} <= codes
    health = client.get("/external/providers/ALI_FARUI/health").json()
    assert health["status"] == "HEALTHY"
    operations = client.get("/external/providers/MOCK_LEGAL_PROVIDER/operations").json()
    assert "ALI_FARUI_LEGAL_RESEARCH_FULL" in operations["operations"]


@pytest.mark.asyncio
async def test_multi_provider_fallback_to_mock(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "farui down"})

    container = container_with_transport(handler, enable_mock_provider=True)
    response = await container.entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert response.provider == ProviderCode.MOCK_LEGAL_PROVIDER
    assert response.data is not None
    assert response.data["summary"].startswith("mock legal fallback")


@pytest.mark.asyncio
async def test_ali_farui_success_uses_primary_provider(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    response = await container_with_transport(
        lambda request: httpx.Response(200, json={"data": {"answer": "ok"}})
    ).entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert response.provider == ProviderCode.ALI_FARUI
