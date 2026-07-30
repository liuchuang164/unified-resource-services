from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.minio, pytest.mark.performance]


@pytest.mark.skipif(
    not (os.getenv("MINIO_ENDPOINT") and os.getenv("CONTROL_DATABASE_URL")),
    reason="real MinIO and control PostgreSQL are required",
)
def test_benchmark_minio_outputs_json() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/benchmark_minio.py", "--count", "3", "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)
    assert "scenarios" in report
    assert report["orphan_count"] == 0
    assert report["duplicate_object_count"] == 0
