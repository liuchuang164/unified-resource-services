import os

import pytest


def require_postgresql_urls() -> tuple[str, str]:
    control_url = os.getenv("CONTROL_DATABASE_URL")
    target_url = os.getenv("POSTGRESQL_ADAPTER_DATABASE_URL") or control_url
    if not control_url or not target_url:
        pytest.skip("real PostgreSQL URLs are required for @pytest.mark.postgresql tests")
    return control_url, target_url
