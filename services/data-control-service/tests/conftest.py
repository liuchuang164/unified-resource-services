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
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
