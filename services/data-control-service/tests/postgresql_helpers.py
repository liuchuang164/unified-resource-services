import os

import pytest


def require_postgresql_urls() -> tuple[str, str]:
    control_url = os.getenv("CONTROL_DATABASE_URL")
    target_url = os.getenv("POSTGRESQL_ADAPTER_DATABASE_URL") or control_url
    if not control_url or not target_url:
        pytest.skip("real PostgreSQL URLs are required for @pytest.mark.postgresql tests")
    return control_url, target_url


def require_migration_urls() -> tuple[str, str]:
    control_url = os.getenv("CONTROL_DATABASE_MIGRATION_URL")
    target_url = (
        os.getenv("TARGET_DATABASE_MIGRATION_URL")
        or os.getenv("POSTGRESQL_ADAPTER_MIGRATION_URL")
        or control_url
    )
    if not control_url or not target_url:
        pytest.skip("real PostgreSQL migration URLs are required")
    return control_url, target_url
