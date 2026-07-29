import os
import subprocess

import pytest

DATABASE_URL = "postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream"
REDIS_URL = "redis://localhost:56379/15"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    environment = {**os.environ, "DATABASE_URL": DATABASE_URL}
    subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
