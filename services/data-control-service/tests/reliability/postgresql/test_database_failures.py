from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.persistence.database import DatabaseManager
from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper
from tests.postgresql_helpers import require_postgresql_urls


@pytest.mark.postgresql
@pytest.mark.reliability
async def test_statement_timeout_rolls_back_and_next_query_recovers() -> None:
    _, target_url = require_postgresql_urls()
    manager = DatabaseManager(
        target_url,
        Settings(app_env="development", database_statement_timeout_ms=100),
        name="target-timeout",
    )
    external_id = f"timeout_{uuid4().hex}"
    try:
        with pytest.raises(DBAPIError) as exc:
            async with manager.session() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            INSERT INTO data_target.platform_records (
                                id, tenant_id, biz_domain, external_id, record_type,
                                title, attributes, version, created_at, updated_at
                            )
                            VALUES (
                                :id, 'tenant_demo', 'demo', :external_id,
                                'demo', 'timeout rollback probe', '{}'::jsonb, 1, now(), now()
                            )
                            """
                        ),
                        {"id": str(uuid4()), "external_id": external_id},
                    )
                    await session.execute(text("SELECT pg_sleep(1)"))
        mapped = PostgreSQLErrorMapper.to_error(exc.value)
        assert mapped.code == "ADAPTER_TIMEOUT"
        async with manager.session() as session:
            count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM data_target.platform_records
                        WHERE tenant_id = 'tenant_demo'
                          AND biz_domain = 'demo'
                          AND external_id = :external_id
                        """
                    ),
                    {"id": str(uuid4()), "external_id": external_id},
                )
            ).scalar_one()
            assert count == 0
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await manager.close()


@pytest.mark.postgresql
@pytest.mark.reliability
async def test_pool_exhaustion_maps_to_unavailable_and_recovers() -> None:
    control_url, _ = require_postgresql_urls()
    manager = DatabaseManager(
        control_url,
        Settings(
            app_env="development",
            database_pool_size=1,
            database_max_overflow=0,
            database_pool_timeout_seconds=1,
        ),
        name="control-pool",
    )
    try:
        async with manager.engine.connect():
            with pytest.raises(DataControlError) as exc:
                await manager.ping()
            assert exc.value.code == "ADAPTER_UNAVAILABLE"
        assert (await manager.ping())["status"] == "ok"
    finally:
        await manager.close()


async def _prepare_lock_rows(manager: DatabaseManager) -> tuple[str, str]:
    first = f"deadlock_a_{uuid4().hex}"
    second = f"deadlock_b_{uuid4().hex}"
    now = datetime.now(UTC)
    async with manager.session() as session:
        async with session.begin():
            for external_id in (first, second):
                await session.execute(
                    text(
                        """
                        INSERT INTO data_target.platform_records (
                            id, tenant_id, biz_domain, external_id, record_type,
                            title, attributes, version, created_at, updated_at
                        )
                        VALUES (
                            :id, 'tenant_demo', 'demo', :external_id,
                            'demo', :title, '{}'::jsonb, 1, :now, :now
                        )
                        ON CONFLICT (tenant_id, biz_domain, external_id)
                        DO UPDATE SET title = EXCLUDED.title, updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "external_id": external_id,
                        "title": external_id,
                        "now": now,
                    },
                )
    return first, second


@pytest.mark.postgresql
@pytest.mark.reliability
async def test_deadlock_maps_to_retryable_deadlock_code() -> None:
    _, target_url = require_postgresql_urls()
    manager = DatabaseManager(
        target_url,
        Settings(app_env="development", database_statement_timeout_ms=5000),
        name="target-deadlock",
    )
    first, second = await _prepare_lock_rows(manager)
    first_locked = asyncio.Event()
    second_locked = asyncio.Event()

    async def lock_in_order(
        own: str, other: str, own_event: asyncio.Event, other_event: asyncio.Event
    ):
        async with manager.session() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE data_target.platform_records
                        SET title = title
                        WHERE tenant_id = 'tenant_demo'
                          AND biz_domain = 'demo'
                          AND external_id = :external_id
                        """
                    ),
                    {"external_id": own},
                )
                own_event.set()
                await asyncio.wait_for(other_event.wait(), timeout=5)
                await session.execute(
                    text(
                        """
                        UPDATE data_target.platform_records
                        SET title = title
                        WHERE tenant_id = 'tenant_demo'
                          AND biz_domain = 'demo'
                          AND external_id = :external_id
                        """
                    ),
                    {"external_id": other},
                )

    try:
        results = await asyncio.gather(
            lock_in_order(first, second, first_locked, second_locked),
            lock_in_order(second, first, second_locked, first_locked),
            return_exceptions=True,
        )
        mapped = [
            PostgreSQLErrorMapper.to_error(result).code
            for result in results
            if isinstance(result, Exception)
        ]
        assert "TRANSACTION_DEADLOCK" in mapped
        assert (await manager.ping())["status"] == "ok"
    finally:
        await manager.close()


@pytest.mark.postgresql
@pytest.mark.reliability
async def test_serialization_failure_maps_to_retryable_serialization_code() -> None:
    _, target_url = require_postgresql_urls()
    manager = DatabaseManager(
        target_url,
        Settings(app_env="development", database_statement_timeout_ms=5000),
        name="target-serializable",
    )
    external_id = f"serial_{uuid4().hex}"
    await _prepare_lock_rows(manager)
    async with manager.session() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO data_target.platform_records (
                        id, tenant_id, biz_domain, external_id, record_type,
                        title, attributes, version, created_at, updated_at
                    )
                    VALUES (
                        :id, 'tenant_demo', 'demo', :external_id,
                        'demo', 'serial', '{}'::jsonb, 1, now(), now()
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"id": str(uuid4()), "external_id": external_id},
            )

    barrier = asyncio.Event()
    reads = 0
    reads_lock = asyncio.Lock()

    async def serializable_update(title: str):
        nonlocal reads
        async with manager.engine.connect() as connection:
            await connection.execution_options(isolation_level="SERIALIZABLE")
            trans = await connection.begin()
            try:
                await connection.execute(
                    text(
                        """
                        SELECT version
                        FROM data_target.platform_records
                        WHERE tenant_id = 'tenant_demo'
                          AND biz_domain = 'demo'
                          AND external_id = :external_id
                        """
                    ),
                    {"external_id": external_id},
                )
                async with reads_lock:
                    reads += 1
                    if reads == 2:
                        barrier.set()
                await asyncio.wait_for(barrier.wait(), timeout=5)
                await connection.execute(
                    text(
                        """
                        UPDATE data_target.platform_records
                        SET title = :title, version = version + 1
                        WHERE tenant_id = 'tenant_demo'
                          AND biz_domain = 'demo'
                          AND external_id = :external_id
                        """
                    ),
                    {"external_id": external_id, "title": title},
                )
                await trans.commit()
            except Exception:
                await trans.rollback()
                raise

    try:
        results = await asyncio.gather(
            serializable_update("a"),
            serializable_update("b"),
            return_exceptions=True,
        )
        mapped = [
            PostgreSQLErrorMapper.to_error(result).code
            for result in results
            if isinstance(result, Exception)
        ]
        assert "TRANSACTION_SERIALIZATION_FAILURE" in mapped
        assert (await manager.ping())["status"] == "ok"
    finally:
        await manager.close()
