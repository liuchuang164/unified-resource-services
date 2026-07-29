from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.infrastructure.persistence.database import DatabaseManager
from data_control_service.infrastructure.persistence.repositories.sqlalchemy_idempotency import (
    SQLAlchemyIdempotencyRepository,
)
from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimState,
    IdempotencyScope,
)
from tests.postgresql_helpers import require_postgresql_urls


@pytest.mark.postgresql
async def test_postgresql_idempotency_claim_replay_and_conflict() -> None:
    control_url, _ = require_postgresql_urls()
    manager = DatabaseManager(control_url, Settings(app_env="test"), name="control-test")
    repository = SQLAlchemyIdempotencyRepository(
        manager.session_factory, processing_timeout_seconds=1
    )
    scope = IdempotencyScope(
        tenant_id="tenant_demo",
        biz_domain="demo",
        operation=Operation.CREATE,
        target=DataTarget.POSTGRESQL,
        idempotency_key=f"idem_pg_{datetime.now(UTC).timestamp()}",
    )
    try:
        claim = await repository.claim(scope, "a" * 64, datetime.now(UTC) + timedelta(hours=1))
        assert claim.state == IdempotencyClaimState.CLAIMED
        assert claim.owner_token
        await repository.mark_succeeded(
            claim.record_id,
            claim.owner_token,
            {
                "request_id": "req_pg_repo",
                "trace_id": "trace_pg_repo",
                "success": True,
                "code": "OK",
                "message": "success",
                "data": {"resource_id": "doc_pg"},
                "meta": {},
            },
        )
        replay = await repository.claim(scope, "a" * 64, datetime.now(UTC) + timedelta(hours=1))
        assert replay.state == IdempotencyClaimState.REPLAY_SUCCEEDED
        conflict = await repository.claim(scope, "b" * 64, datetime.now(UTC) + timedelta(hours=1))
        assert conflict.state == IdempotencyClaimState.FINGERPRINT_CONFLICT
    finally:
        await manager.close()


@pytest.mark.postgresql
async def test_database_manager_exposes_async_session_factory() -> None:
    control_url, _ = require_postgresql_urls()
    manager = DatabaseManager(control_url, Settings(app_env="test"), name="control-test")
    try:
        assert isinstance(manager.session_factory, async_sessionmaker)
        assert (await manager.ping())["status"] == "ok"
    finally:
        await manager.close()
