from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.redis, pytest.mark.performance]


@pytest.mark.skipif(
    not (os.getenv("REDIS_URL") and os.getenv("CONTROL_DATABASE_URL")),
    reason="real Redis and control PostgreSQL are required",
)
def test_benchmark_redis_outputs_json() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/benchmark_redis.py", "--count", "3", "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)
    assert "scenarios" in report
    assert report["duplicate_write_count"] == 0
