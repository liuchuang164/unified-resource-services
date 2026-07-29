from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.postgresql_helpers import require_migration_urls


def _run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command, check=True, env=env, text=True, capture_output=True
    )


@pytest.mark.migration
def test_control_migration_upgrade_downgrade_roundtrip() -> None:
    control_url, _ = require_migration_urls()
    env = {**os.environ, "CONTROL_DATABASE_MIGRATION_URL": control_url}
    _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "upgrade", "head"], env)
    current = _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "current"], env)
    assert "0005" in current.stdout
    _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "downgrade", "-1"], env)
    _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "upgrade", "head"], env)
    current = _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "current"], env)
    assert "0005" in current.stdout


@pytest.mark.migration
def test_target_migration_upgrade_downgrade_roundtrip() -> None:
    _, target_url = require_migration_urls()
    env = {**os.environ, "TARGET_DATABASE_MIGRATION_URL": target_url}
    _run([sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "upgrade", "head"], env)
    current = _run([sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "current"], env)
    assert "target_0001" in current.stdout
    _run([sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "downgrade", "-1"], env)
    _run([sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "upgrade", "head"], env)
    current = _run([sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "current"], env)
    assert "target_0001" in current.stdout
