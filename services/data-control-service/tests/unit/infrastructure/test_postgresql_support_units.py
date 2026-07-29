from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from tests.integration.test_transaction_orchestrator import command

from data_control_service.adapters.postgresql import SQLAlchemyPostgreSQLAdapter
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.idempotency.in_memory import InMemoryIdempotencyRepository
from data_control_service.infrastructure.persistence.database import (
    redact_database_url,
    require_database_url,
)
from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper
from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimState,
    IdempotencyScope,
)


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
    existing = DataControlError("RESOURCE_NOT_FOUND")
    assert PostgreSQLErrorMapper.to_error(existing) is existing
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
    assert (
        PostgreSQLErrorMapper.to_error(DBAPIError("stmt", {}, _Original("57014"))).code
        == "ADAPTER_TIMEOUT"
    )
    assert (
        PostgreSQLErrorMapper.to_error(DBAPIError("stmt", {}, _Original("53300"))).code
        == "ADAPTER_UNAVAILABLE"
    )
    assert (
        PostgreSQLErrorMapper.to_error(DBAPIError("stmt", {}, _Original("40P01"))).code
        == "TRANSACTION_DEADLOCK"
    )
    assert PostgreSQLErrorMapper.to_error(RuntimeError("boom")).code == "INTERNAL_ERROR"


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


async def test_sqlalchemy_postgresql_adapter_rejects_invalid_read_write_shapes() -> None:
    adapter = SQLAlchemyPostgreSQLAdapter.__new__(SQLAlchemyPostgreSQLAdapter)
    adapter._max_batch_size = 1
    table = SQLAlchemyPostgreSQLAdapter._table(
        _postgresql_command({"external_id": "doc_1"})
        .validated_payload["resource_mapping"]
        .physical_mapping
    )

    with pytest.raises(DataControlError) as get_exc:
        await adapter._get(object(), table, _postgresql_command({}), {})
    assert get_exc.value.code == "REQUEST_SCHEMA_INVALID"

    with pytest.raises(DataControlError) as list_filter_exc:
        await adapter._list(
            object(),
            table,
            _postgresql_command({}),
            {"forbidden": "value"},
            {},
        )
    assert list_filter_exc.value.code == "FIELD_ACCESS_DENIED"

    with pytest.raises(DataControlError) as list_sort_exc:
        await adapter._list(
            object(),
            table,
            _postgresql_command({}),
            {},
            {"sort": "forbidden"},
        )
    assert list_sort_exc.value.code == "FIELD_ACCESS_DENIED"

    with pytest.raises(DataControlError) as update_exc:
        await adapter._update(object(), table, _postgresql_command({}), {})
    assert update_exc.value.code == "REQUEST_SCHEMA_INVALID"

    with pytest.raises(DataControlError) as delete_exc:
        await adapter._delete(object(), table, _postgresql_command({}))
    assert delete_exc.value.code == "REQUEST_SCHEMA_INVALID"

    batch_cmd = _postgresql_command({"items": [{"external_id": "a"}, {"external_id": "b"}]})
    batch_cmd = replace(batch_cmd, operation=Operation.BATCH)
    with pytest.raises(DataControlError) as batch_exc:
        await adapter._execute_in_session(object(), batch_cmd)
    assert batch_exc.value.code == "PAYLOAD_TOO_LARGE"


async def test_in_memory_idempotency_recovery_state_transitions() -> None:
    repo = InMemoryIdempotencyRepository()
    scope = IdempotencyScope(
        tenant_id="tenant_demo",
        biz_domain="demo",
        operation=Operation.CREATE,
        target=DataTarget.POSTGRESQL,
        idempotency_key="idem_recovery_unit",
    )
    claim = await repo.claim(
        scope,
        request_fingerprint="fingerprint",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert claim.state == IdempotencyClaimState.CLAIMED
    assert claim.owner_token is not None

    await repo.mark_recovery_required(
        claim.record_id,
        claim.owner_token,
        business_result_reference={"resource_id": "doc_1"},
        recovery_strategy="MARK_SUCCEEDED_FROM_BUSINESS_RESULT",
        recovery_metadata={"step": "unit"},
        error_code="IDEMPOTENCY_RECOVERY_REQUIRED",
        max_recovery_attempts=2,
    )
    recovery_claim = await repo.claim(
        scope,
        request_fingerprint="fingerprint",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert recovery_claim.state == IdempotencyClaimState.RECOVERY_REQUIRED

    rows = await repo.list_recovery_required(limit=10)
    assert rows[0]["business_result_reference"] == {"resource_id": "doc_1"}

    await repo.mark_recovery_failed(
        claim.record_id,
        error_code="RECOVERY_FAILED",
        recovery_metadata={"attempt": 1},
    )
    await repo.mark_recovery_succeeded(
        claim.record_id,
        {"success": True},
        recovery_metadata={"attempt": 2},
    )
    replay = await repo.claim(
        scope,
        request_fingerprint="fingerprint",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert replay.state == IdempotencyClaimState.REPLAY_SUCCEEDED
    assert replay.response_snapshot == {"success": True}


async def test_in_memory_idempotency_ignores_stale_or_unknown_recovery_updates() -> None:
    repo = InMemoryIdempotencyRepository()
    await repo.mark_recovery_succeeded("missing", {"success": True}, recovery_metadata={})
    await repo.mark_recovery_failed("missing", error_code="RECOVERY_FAILED", recovery_metadata={})

    scope = IdempotencyScope(
        tenant_id="tenant_demo",
        biz_domain="demo",
        operation=Operation.CREATE,
        target=DataTarget.POSTGRESQL,
        idempotency_key="idem_wrong_owner",
    )
    claim = await repo.claim(
        scope,
        request_fingerprint="fingerprint",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await repo.mark_recovery_required(
        claim.record_id,
        "wrong-owner",
        business_result_reference={"resource_id": "doc_1"},
        recovery_strategy="MARK_SUCCEEDED_FROM_BUSINESS_RESULT",
        recovery_metadata={},
        error_code="IDEMPOTENCY_RECOVERY_REQUIRED",
        max_recovery_attempts=2,
    )
    still_processing = await repo.claim(
        scope,
        request_fingerprint="fingerprint",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert still_processing.state == IdempotencyClaimState.IN_PROGRESS
    assert await repo.health() == {"status": "ok", "backend": "in_memory"}
