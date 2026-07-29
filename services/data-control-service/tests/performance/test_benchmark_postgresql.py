from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from tests.postgresql_helpers import require_postgresql_urls


@pytest.mark.postgresql
@pytest.mark.performance
def test_benchmark_postgresql_outputs_required_cases() -> None:
    require_postgresql_urls()
    env = {**os.environ}
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/benchmark_postgresql.py",
            "--get-count",
            "2",
            "--upsert-count",
            "2",
            "--concurrent-different-count",
            "2",
            "--concurrent-same-count",
            "2",
            "--batch-count",
            "2",
            "--replay-count",
            "2",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = json.loads(result.stdout)
    assert output["duplicate_write_count"] == 0
    assert output["pool_timeout_count"] == 0
    assert [case["name"] for case in output["results"]] == [
        "1000_get_serial",
        "1000_upsert_serial",
        "100_concurrent_different_keys",
        "20_concurrent_same_key",
        "100_atomic_batch",
        "500_idempotency_replay",
    ]
