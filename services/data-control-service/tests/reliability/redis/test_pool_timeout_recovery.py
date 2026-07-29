from __future__ import annotations

import os

import pytest

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.redis.error_mapper import RedisErrorMapper
from data_control_service.infrastructure.redis.manager import RedisManager

pytestmark = [pytest.mark.redis, pytest.mark.reliability]


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="real Redis is required")
async def test_redis_pool_exhaustion_recovers() -> None:
    manager = RedisManager(
        Settings(
            redis_adapter_enabled=True,
            redis_url=os.environ["REDIS_URL"],
            redis_max_connections=1,
            redis_socket_timeout_seconds=0.2,
            redis_socket_connect_timeout_seconds=0.2,
        )
    )
    await manager.start()
    pool = manager.client().connection_pool
    connection = await pool.get_connection()
    try:
        with pytest.raises(DataControlError) as exc:
            try:
                await manager.client().ping()
            except Exception as raw:
                raise RedisErrorMapper.to_error(raw) from raw
        assert exc.value.code in {"ADAPTER_CAPACITY_EXCEEDED", "ADAPTER_TIMEOUT"}
    finally:
        await pool.release(connection)
        await manager.close()

    recovered = RedisManager(
        Settings(redis_adapter_enabled=True, redis_url=os.environ["REDIS_URL"])
    )
    try:
        assert (await recovered.ping())["status"] == "ok"
    finally:
        await recovered.close()


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="real Redis is required")
async def test_redis_timeout_mapping_and_recovery() -> None:
    manager = RedisManager(
        Settings(
            redis_adapter_enabled=True,
            redis_url=os.environ["REDIS_URL"],
            redis_socket_timeout_seconds=0.001,
            redis_socket_connect_timeout_seconds=0.2,
        )
    )
    try:
        with pytest.raises(DataControlError) as exc:
            try:
                await manager.client().blpop("dcs:test:timeout", timeout=1)
            except Exception as raw:
                raise RedisErrorMapper.to_error(raw) from raw
        assert exc.value.code in {"ADAPTER_TIMEOUT", "ADAPTER_UNAVAILABLE"}
    finally:
        await manager.close()

    recovered = RedisManager(
        Settings(redis_adapter_enabled=True, redis_url=os.environ["REDIS_URL"])
    )
    try:
        assert (await recovered.ping())["status"] == "ok"
    finally:
        await recovered.close()
