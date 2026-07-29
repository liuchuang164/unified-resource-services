from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.persistence.database import DatabaseManager
from tests.postgresql_helpers import require_postgresql_urls


def _compose(command: list[str]) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is required for dedicated stop/start reliability tests")
    subprocess.run(  # noqa: S603
        [docker, "compose", "-f", "docker-compose.reliability.yml", *command],
        check=True,
        capture_output=True,
        text=True,
    )


def _wait_compose_ready(service: str) -> None:
    for _ in range(30):
        try:
            _compose(["exec", "-T", service, "pg_isready", "-U", "data_control"])
            return
        except subprocess.CalledProcessError:
            time.sleep(2)
    _compose(["ps"])
    raise AssertionError(f"{service} did not become ready")


@pytest.mark.postgresql
@pytest.mark.reliability
async def test_dedicated_postgresql_stop_start_recovers_readiness() -> None:
    if os.getenv("POSTGRESQL_RELIABILITY_COMPOSE") != "1":
        pytest.skip("dedicated reliability compose control is not enabled")
    _, target_url = require_postgresql_urls()
    manager = DatabaseManager(target_url, Settings(app_env="test"), name="target-stop-start")
    try:
        assert (await manager.ping())["status"] == "ok"
        _compose(["stop", "postgres-target"])
        with pytest.raises(DataControlError) as exc:
            await manager.ping()
        assert exc.value.code == "ADAPTER_UNAVAILABLE"
        _compose(["start", "postgres-target"])
        _wait_compose_ready("postgres-target")
        assert (await manager.ping())["status"] == "ok"
    finally:
        await manager.close()
