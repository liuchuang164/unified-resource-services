from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from external_access_service.bootstrap import Container, build_container
from external_access_service.domain.models import (
    AuthContext,
    BizContext,
    DispatchPolicy,
    ExternalDispatchRequest,
    ProviderCode,
    ProviderRef,
    RequestSource,
)
from external_access_service.infrastructure.config import Settings
from external_access_service.infrastructure.providers.ali_farui import farui_mock_transport
from external_access_service.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", allow_fake_credentials=True)


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture
def client(container: Container, settings: Settings) -> TestClient:
    return TestClient(create_app(container, settings))


@pytest.fixture
def capability_token(container: Container) -> str:
    return container.capability.issue_for_test(
        {
            "issuer": "hermes",
            "tenant_id": "tenant_A",
            "biz_domain": "LEGAL",
            "allowed_operations": [
                "legal_consult",
                "law_search",
                "case_search",
                "legal_research_full",
            ],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
    )


@pytest.fixture
def dispatch_payload() -> Callable[..., dict[str, Any]]:
    def factory(**changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": "req_001",
            "trace_id": "trace_001",
            "request_source": "BUSINESS_SERVICE",
            "auth_context": {"tenant_id": "tenant_A", "user_id": "user_001", "roles": ["LAWYER"]},
            "biz_context": {"biz_domain": "LEGAL", "biz_scene": "LEGAL_RESEARCH"},
            "operation": "ALI_FARUI_LEGAL_RESEARCH_FULL",
            "provider": {"provider_code": "ALI_FARUI", "capability": "LEGAL_RESEARCH"},
            "payload": {"query": "民间借贷纠纷法律依据"},
            "policy": {"timeout_ms": 3000, "retry": {"enabled": True, "max_attempts": 2}},
        }
        payload.update(changes)
        return payload

    return factory


@pytest.fixture
def dispatch_request() -> Callable[..., ExternalDispatchRequest]:
    def factory(**changes: Any) -> ExternalDispatchRequest:
        request = ExternalDispatchRequest(
            request_id="req_001",
            trace_id="trace_001",
            request_source=RequestSource.BUSINESS_SERVICE,
            auth_context=AuthContext(tenant_id="tenant_A", user_id="user_001", roles=("LAWYER",)),
            biz_context=BizContext(biz_domain="LEGAL", biz_scene="LEGAL_RESEARCH"),
            operation="ALI_FARUI_LEGAL_RESEARCH_FULL",
            provider=ProviderRef(provider_code=ProviderCode.ALI_FARUI, capability="LEGAL_RESEARCH"),
            payload={"query": "民间借贷纠纷法律依据"},
            policy=DispatchPolicy(timeout_ms=3000),
        )
        return request.model_copy(update=changes)

    return factory


def container_with_transport(handler: Callable[[httpx.Request], httpx.Response]) -> Container:
    client = httpx.AsyncClient(
        base_url="https://farui.example.invalid",
        transport=farui_mock_transport(handler),
    )
    return build_container(Settings(environment="test", allow_fake_credentials=True), client)
