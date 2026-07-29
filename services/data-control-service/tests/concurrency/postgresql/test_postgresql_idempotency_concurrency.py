import asyncio
from datetime import UTC, datetime, timedelta

import pytest

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
async def test_two_repository_instances_claim_same_key_once() -> None:
    control_url, _ = require_postgresql_urls()
    first_manager = DatabaseManager(control_url, Settings(app_env="test"), name="control-a")
    second_manager = DatabaseManager(control_url, Settings(app_env="test"), name="control-b")
    scope = IdempotencyScope(
        tenant_id="tenant_demo",
        biz_domain="demo",
        operation=Operation.CREATE,
        target=DataTarget.POSTGRESQL,
        idempotency_key=f"idem_pg_concurrent_{datetime.now(UTC).timestamp()}",
    )
    try:
        first = SQLAlchemyIdempotencyRepository(
            first_manager.session_factory, processing_timeout_seconds=120
        )
        second = SQLAlchemyIdempotencyRepository(
            second_manager.session_factory, processing_timeout_seconds=120
        )
        results = await asyncio.gather(
            *[
                repository.claim(scope, "c" * 64, datetime.now(UTC) + timedelta(hours=1))
                for repository in [first, second] * 10
            ]
        )
        assert sum(result.state == IdempotencyClaimState.CLAIMED for result in results) == 1
        assert sum(result.state == IdempotencyClaimState.IN_PROGRESS for result in results) == 19
    finally:
        await first_manager.close()
        await second_manager.close()
