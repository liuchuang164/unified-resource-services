import pytest
from httpx import AsyncClient

from data_control_service.app import create_app
from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from tests.integration.test_dispatch_pipeline import base_request


async def test_request_body_roles_are_rejected(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["roles"] = ["DATA_CONTROL_ADMIN"]
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_request_body_permissions_are_rejected(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["permissions"] = ["data:record:write"]
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_tenant_mismatch_is_rejected(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["tenant_id"] = "tenant_other"
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_biz_domain_outside_principal_scope_is_rejected(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["biz_domain"] = "other"
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_actor_mismatch_is_rejected(client: AsyncClient) -> None:
    request = base_request()
    request["auth_context"]["actor"]["id"] = "svc_other"
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_missing_authentication_returns_auth_required() -> None:
    app = create_app()
    from httpx import ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/data/dispatch", json=base_request())
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_development_auth_provider_cannot_start_in_production() -> None:
    with pytest.raises(DataControlError):
        create_app(Settings(app_env="production", auth_provider="development"))
