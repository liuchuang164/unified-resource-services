import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from file_media_stream_service.adapters.persistence.postgres import PostgresHealth
from file_media_stream_service.bootstrap import (
    ProductionContainer,
    build_container,
    build_production_container,
)
from file_media_stream_service.config import Settings
from file_media_stream_service.main import create_app

pytestmark = pytest.mark.production_integration


def production_settings() -> Settings:
    return Settings(
        environment="production",
        infrastructure_mode="production",
        database_url=(
            "postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream"
        ),
        redis_url="redis://localhost:56379/13",
        minio_endpoint="localhost:59000",
        minio_access_key="fms_local",
        minio_secret_key="fms_local_only_secret",
        minio_bucket="file-media-stream",
        minio_secure=False,
    )


@pytest.mark.asyncio
async def test_production_composition_readiness_and_transaction() -> None:
    container = build_container(production_settings())
    assert isinstance(container, ProductionContainer)
    assert await container.readiness.check() == {
        "postgres": "ok",
        "redis": "ok",
        "minio": "ok",
    }
    await container.transaction.commit()
    await container.transaction.rollback()
    await container.transaction.close()
    postgres = container.readiness.postgres
    assert isinstance(postgres, PostgresHealth)
    await postgres.engine.dispose()
    redis = container.readiness.redis
    await redis.client.aclose()  # type: ignore[attr-defined]


def test_production_http_health_and_ready_are_non_sensitive() -> None:
    container = build_production_container(production_settings())
    client = TestClient(create_app(container, production_settings()))
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgres": "ok", "redis": "ok", "minio": "ok"},
    }
    rendered = response.text
    for secret in ("fms_local_only", "localhost:55432", "localhost:56379"):
        assert secret not in rendered


def test_production_configuration_fails_fast() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(environment="production", infrastructure_mode="production")
    with pytest.raises(RuntimeError, match="Production container"):
        build_production_container(Settings(environment="development"))
