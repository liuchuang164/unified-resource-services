import pytest
from httpx import ASGITransport, AsyncClient

from data_control_service.api.dependencies import get_data_control_service
from data_control_service.app import create_app


@pytest.fixture(autouse=True)
def reset_service_cache() -> None:
    get_data_control_service.cache_clear()


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "x-dev-subject-id": "svc_demo",
            "x-dev-tenant-id": "tenant_demo",
            "x-dev-biz-domains": "demo",
            "x-dev-permissions": (
                "data:record:read,data:record:write,data:object:read,data:object:write,"
                "data:cache:read,data:cache:write,data:graph:read,data:graph:write,"
                "data:vector:read,data:vector:write,data:timeseries:read,"
                "data:timeseries:write,data:high-risk:execute"
            ),
        },
    ) as async_client:
        yield async_client
