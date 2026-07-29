from __future__ import annotations

import os
import subprocess
import sys


def _run(command: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)  # noqa: S603


def main() -> None:
    control_url = os.getenv("CONTROL_DATABASE_MIGRATION_URL")
    target_url = os.getenv("TARGET_DATABASE_MIGRATION_URL") or os.getenv(
        "POSTGRESQL_ADAPTER_MIGRATION_URL"
    )
    if not control_url or not target_url:
        raise SystemExit(
            "CONTROL_DATABASE_MIGRATION_URL and TARGET_DATABASE_MIGRATION_URL are required"
        )
    env = os.environ.copy()
    _run([sys.executable, "-m", "alembic", "-c", "alembic-control.ini", "stamp", "0004"], env=env)
    _run(
        [sys.executable, "-m", "alembic", "-c", "alembic-target.ini", "stamp", "target_0001"],
        env=env,
    )


if __name__ == "__main__":
    main()
