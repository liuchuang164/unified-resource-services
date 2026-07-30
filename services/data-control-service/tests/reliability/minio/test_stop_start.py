from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from data_control_service.api.dependencies import (
    get_control_database_manager,
    get_data_control_service,
    get_minio_manager,
    get_redis_manager,
    get_settings,
    get_target_postgresql_manager,
)
from data_control_service.app import create_app
from tests.integration.minio.test_dispatch_pipeline import _request, _txt_payload

pytestmark = [pytest.mark.minio, pytest.mark.reliability]


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", "docker-compose.minio.yml", *args],  # noqa: S607
        check=False,
        text=True,
        capture_output=True,
    )


async def _client() -> AsyncClient:
    get_settings.cache_clear()
    get_control_database_manager.cache_clear()
    get_target_postgresql_manager.cache_clear()
    get_redis_manager.cache_clear()
    get_minio_manager.cache_clear()
    get_data_control_service.cache_clear()
    return AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        headers={
            "x-dev-subject-id": "svc_demo",
            "x-dev-tenant-id": "tenant_demo",
            "x-dev-biz-domains": "demo",
            "x-dev-permissions": "data:asset:read,data:asset:write,data:high-risk:execute",
        },
    )


@pytest.mark.skipif(
    os.getenv("MINIO_RELIABILITY_COMPOSE") != "1" or shutil.which("docker") is None,
    reason="dedicated minio compose is required",
)
async def test_minio_stop_start_readiness_and_recovery() -> None:
    async with await _client() as client:
        ready = await client.get("/health/ready")
        create = await client.post(
            "/data/dispatch", json=_request("CREATE", _txt_payload(), f"idem_{uuid4().hex}")
        )
        assert ready.status_code == 200
        assert create.status_code == 200
        object_id = create.json()["data"]["logical_object_id"]

        assert _compose("stop", "minio").returncode == 0
        live = await client.get("/health/live")
        not_ready = await client.get("/health/ready")
        failed = await client.post(
            "/data/dispatch", json=_request("PRESIGN_DOWNLOAD", {"logical_object_id": object_id})
        )
        assert live.status_code == 200
        assert not_ready.status_code == 503
        assert failed.json()["code"] in {"ADAPTER_UNAVAILABLE", "ADAPTER_TIMEOUT"}

        assert _compose("start", "minio").returncode == 0
        for _ in range(30):
            recovered = await client.get("/health/ready")
            if recovered.status_code == 200:
                break
            await asyncio.sleep(1)
        assert recovered.status_code == 200
        recovered_operation = await client.post(
            "/data/dispatch",
            json=_request("PRESIGN_DOWNLOAD", {"logical_object_id": object_id}),
        )
        assert recovered_operation.status_code == 200
