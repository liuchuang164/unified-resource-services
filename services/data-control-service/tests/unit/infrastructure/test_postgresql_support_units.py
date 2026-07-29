from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from tests.integration.test_transaction_orchestrator import command

from data_control_service.adapters.postgresql import SQLAlchemyPostgreSQLAdapter
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.persistence.database import (
    redact_database_url,
    require_database_url,
)
from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper


class _Original:
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _postgresql_command(data: dict[str, object]):
    base = command(Operation.CREATE, data)
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
    return replace(base, validated_payload={**base.validated_payload, "resource_mapping": mapping})


def test_redact_database_url_hides_password() -> None:
    assert (
        redact_database_url("postgresql+asyncpg://user:secret@example.test:5432/db")
        == "postgresql+asyncpg://user:***@example.test:5432/db"
    )


def test_require_database_url_fails_closed_in_production() -> None:
    with pytest.raises(DataControlError) as exc:
        require_database_url(None, "control", Settings(app_env="production"))
    assert exc.value.code == "CONFIGURATION_INVALID"


def test_postgresql_error_mapper_maps_known_sqlstates() -> None:
    assert (
        PostgreSQLErrorMapper.to_error(IntegrityError("stmt", {}, _Original("23505"))).code
        == "DATA_CONSTRAINT_VIOLATION"
    )
    assert (
        PostgreSQLErrorMapper.to_error(IntegrityError("stmt", {}, _Original("40001"))).code
        == "TRANSACTION_SERIALIZATION_FAILURE"
    )
    assert PostgreSQLErrorMapper.to_error(SQLAlchemyTimeoutError()).code == "ADAPTER_TIMEOUT"
    assert (
        PostgreSQLErrorMapper.to_error(OperationalError("stmt", {}, _Original("08006"))).code
        == "ADAPTER_UNAVAILABLE"
    )


def test_sqlalchemy_postgresql_adapter_rejects_protected_fields() -> None:
    adapter = SQLAlchemyPostgreSQLAdapter.__new__(SQLAlchemyPostgreSQLAdapter)
    cmd = _postgresql_command({"external_id": "doc_1", "tenant_id": "tenant_other"})
    with pytest.raises(DataControlError) as exc:
        adapter._validated_write_data(cmd, cmd.validated_payload["data"], require_external_id=True)
    assert exc.value.code == "REQUEST_SCHEMA_INVALID"


def test_sqlalchemy_postgresql_adapter_rejects_unknown_fields() -> None:
    adapter = SQLAlchemyPostgreSQLAdapter.__new__(SQLAlchemyPostgreSQLAdapter)
    cmd = _postgresql_command({"external_id": "doc_1", "unknown": "x"})
    with pytest.raises(DataControlError) as exc:
        adapter._validated_write_data(cmd, cmd.validated_payload["data"], require_external_id=True)
    assert exc.value.code == "FIELD_ACCESS_DENIED"


def test_sqlalchemy_postgresql_adapter_builds_trusted_table() -> None:
    cmd = _postgresql_command({"external_id": "doc_1", "record_type": "demo"})
    table = SQLAlchemyPostgreSQLAdapter._table(
        cmd.validated_payload["resource_mapping"].physical_mapping
    )
    assert table.schema == "data_target"
    assert table.name == "platform_records"
