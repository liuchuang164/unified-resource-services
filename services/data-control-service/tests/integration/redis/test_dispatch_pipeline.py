from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from data_control_service.api.dependencies import (
    get_control_database_manager,
    get_data_control_service,
    get_redis_manager,
    get_settings,
    get_target_postgresql_manager,
)
from data_control_service.app import create_app

pytestmark = pytest.mark.redis


def _redis_available() -> bool:
    return bool(os.getenv("REDIS_URL") and os.getenv("CONTROL_DATABASE_URL"))


def _request(operation: str, data: dict[str, Any], idem: str | None = None) -> dict[str, Any]:
    key = uuid4().hex
    return {
        "contract_version": "1.0",
        "request_id": f"req_REDIS_{key}",
        "trace_id": f"trace_REDIS_{key}",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": operation,
        "resource": {
            "target": "REDIS",
            "type": "CACHE_ENTRY",
            "name": "cache",
            "resource_id": data.get("logical_key"),
        },
        "payload": {"data": data, "query": {}, "options": {}},
        "idempotency_key": idem,
        "transaction": {"mode": "LOCAL"},
        "timeout_ms": 5000,
        "metadata": {"caller_service": "test"},
    }


async def _client() -> AsyncClient:
    get_settings.cache_clear()
    get_control_database_manager.cache_clear()
    get_target_postgresql_manager.cache_clear()
    get_redis_manager.cache_clear()
    get_data_control_service.cache_clear()
    app = create_app()
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "x-dev-subject-id": "svc_demo",
            "x-dev-tenant-id": "tenant_demo",
            "x-dev-biz-domains": "demo",
            "x-dev-permissions": "data:cache:read,data:cache:write,data:high-risk:execute",
        },
    )


@pytest.mark.skipif(not _redis_available(), reason="real Redis and control PostgreSQL are required")
async def test_redis_upsert_get_exists_delete_over_dispatch() -> None:
    logical_key = f"it_{uuid4().hex}"
    async with await _client() as client:
        upsert = await client.post(
            "/data/dispatch",
            json=_request(
                "UPSERT",
                {"logical_key": logical_key, "value": {"hello": "redis"}, "ttl_seconds": 60},
                f"idem_{uuid4().hex}",
            ),
        )
        exists = await client.post(
            "/data/dispatch", json=_request("EXISTS", {"logical_key": logical_key})
        )
        get = await client.post(
            "/data/dispatch", json=_request("GET", {"logical_key": logical_key})
        )
        delete = await client.post(
            "/data/dispatch",
            json=_request("DELETE", {"logical_key": logical_key}, f"idem_{uuid4().hex}"),
        )
        missing = await client.post(
            "/data/dispatch", json=_request("EXISTS", {"logical_key": logical_key})
        )

    assert upsert.status_code == 200
    assert exists.json()["data"]["exists"] is True
    assert get.json()["data"]["value"] == {"hello": "redis"}
    assert delete.json()["data"]["deleted"] is True
    assert missing.json()["data"]["exists"] is False


@pytest.mark.skipif(not _redis_available(), reason="real Redis and control PostgreSQL are required")
async def test_redis_ttl_and_lock_unlock_over_dispatch() -> None:
    logical_key = f"ttl_{uuid4().hex}"
    lock_key = f"lock_{uuid4().hex}"
    lock_token = "redis-lock-" + uuid4().hex
    async with await _client() as client:
        ttl_zero = await client.post(
            "/data/dispatch",
            json=_request(
                "UPSERT",
                {"logical_key": logical_key, "value": {"v": 1}, "ttl_seconds": 0},
                f"idem_{uuid4().hex}",
            ),
        )
        lock = await client.post(
            "/data/dispatch",
            json=_request(
                "LOCK",
                {"logical_key": lock_key, "lock_token": lock_token, "ttl_seconds": 30},
                f"idem_{uuid4().hex}",
            ),
        )
        wrong_unlock = await client.post(
            "/data/dispatch",
            json=_request(
                "UNLOCK",
                {"logical_key": lock_key, "lock_token": "redis-lock-" + uuid4().hex},
                f"idem_{uuid4().hex}",
            ),
        )
        unlock = await client.post(
            "/data/dispatch",
            json=_request(
                "UNLOCK",
                {"logical_key": lock_key, "lock_token": lock_token},
                f"idem_{uuid4().hex}",
            ),
        )

    assert ttl_zero.status_code == 400
    assert ttl_zero.json()["code"] == "REQUEST_SCHEMA_INVALID"
    assert lock.status_code == 200
    assert wrong_unlock.status_code == 409
    assert wrong_unlock.json()["code"] == "LOCK_TOKEN_MISMATCH"
    assert unlock.status_code == 200
    assert unlock.json()["data"]["unlocked"] is True


@pytest.mark.skipif(not _redis_available(), reason="real Redis and control PostgreSQL are required")
async def test_redis_idempotency_replay_does_not_extend_lock() -> None:
    logical_key = f"idem_lock_{uuid4().hex}"
    token = "redis-lock-" + uuid4().hex
    idem = f"idem_{uuid4().hex}"
    payload = _request(
        "LOCK",
        {"logical_key": logical_key, "lock_token": token, "ttl_seconds": 30},
        idem,
    )
    async with await _client() as client:
        first = await client.post("/data/dispatch", json=payload)
        replay = await client.post("/data/dispatch", json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["meta"]["idempotency_replayed"] is True
