from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from tests.integration.redis.test_dispatch_pipeline import _request

from data_control_service.api.dependencies import (
    get_control_database_manager,
    get_data_control_service,
    get_redis_manager,
    get_settings,
    get_target_postgresql_manager,
)
from data_control_service.app import create_app

pytestmark = [pytest.mark.redis, pytest.mark.reliability]


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", "docker-compose.redis.yml", *args],  # noqa: S607
        check=False,
        text=True,
        capture_output=True,
    )


async def _client() -> AsyncClient:
    get_settings.cache_clear()
    get_control_database_manager.cache_clear()
    get_target_postgresql_manager.cache_clear()
    get_redis_manager.cache_clear()
    get_data_control_service.cache_clear()
    return AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        headers={
            "x-dev-subject-id": "svc_demo",
            "x-dev-tenant-id": "tenant_demo",
            "x-dev-biz-domains": "demo",
            "x-dev-permissions": "data:cache:read,data:cache:write,data:high-risk:execute",
        },
    )


@pytest.mark.skipif(
    os.getenv("REDIS_RELIABILITY_COMPOSE") != "1" or shutil.which("docker") is None,
    reason="dedicated redis compose is required",
)
async def test_redis_stop_start_readiness_and_recovery() -> None:
    logical_key = f"stop_{uuid4().hex}"
    async with await _client() as client:
        ready = await client.get("/health/ready")
        write = await client.post(
            "/data/dispatch",
            json=_request(
                "UPSERT",
                {"logical_key": logical_key, "value": {"before": True}, "ttl_seconds": 60},
                f"idem_{uuid4().hex}",
            ),
        )
        assert ready.status_code == 200
        assert write.status_code == 200

        assert _compose("stop", "redis").returncode == 0
        live = await client.get("/health/live")
        not_ready = await client.get("/health/ready")
        failed = await client.post(
            "/data/dispatch",
            json=_request("GET", {"logical_key": logical_key}),
        )
        assert live.status_code == 200
        assert not_ready.status_code == 503
        assert failed.json()["code"] in {"ADAPTER_UNAVAILABLE", "ADAPTER_TIMEOUT"}

        assert _compose("start", "redis").returncode == 0
        for _ in range(30):
            recovered = await client.get("/health/ready")
            if recovered.status_code == 200:
                break
            await asyncio.sleep(1)
        assert recovered.status_code == 200
