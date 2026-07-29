from dataclasses import replace

import pytest

from data_control_service.adapters.postgresql import SQLAlchemyPostgreSQLAdapter
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.persistence.database import DatabaseManager
from tests.integration.test_transaction_orchestrator import command
from tests.postgresql_helpers import require_postgresql_urls
from tests.unit.application.test_idempotency_concurrency import context


def postgresql_mapping_command(operation: Operation, data: dict[str, object]):
    base = command(operation, data)
    mapping = replace(
        base.validated_payload["resource_mapping"],
        physical_mapping={
            "schema": "data_target",
            "table": "platform_records",
            "primary_key": "id",
            "field_allowlist": ["external_id", "record_type", "title", "content", "attributes"],
            "filter_allowlist": ["external_id", "record_type"],
            "sort_allowlist": ["updated_at", "external_id"],
            "max_page_size": 100,
            "upsert_conflict_columns": ["tenant_id", "biz_domain", "external_id"],
        },
    )
    return replace(
        base,
        validated_payload={**base.validated_payload, "resource_mapping": mapping},
    )


@pytest.mark.postgresql
async def test_postgresql_adapter_rejects_scope_override_before_database_write() -> None:
    _, target_url = require_postgresql_urls()
    manager = DatabaseManager(target_url, Settings(app_env="test"), name="target-test")
    adapter = SQLAlchemyPostgreSQLAdapter(manager.session_factory)
    try:
        with pytest.raises(DataControlError) as exc:
            await adapter.execute(
                postgresql_mapping_command(
                    Operation.CREATE,
                    {
                        "external_id": "doc_bad",
                        "record_type": "demo",
                        "tenant_id": "tenant_other",
                    },
                ),
                context(),
            )
        assert exc.value.code == "REQUEST_SCHEMA_INVALID"
    finally:
        await manager.close()
