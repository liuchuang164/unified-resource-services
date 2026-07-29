from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from httpx import AsyncClient
from tests.integration.test_dispatch_pipeline import base_request

pytestmark = pytest.mark.redis


def redis_request(data: dict[str, object], operation: str = "UPSERT") -> dict[str, object]:
    request = base_request(
        operation=operation,
        resource={
            "target": "REDIS",
            "type": "CACHE_ENTRY",
            "name": "cache",
            "resource_id": str(data.get("logical_key", f"k_{uuid4().hex}")),
        },
        payload={"data": data, "query": {}, "options": {}},
        idempotency_key=f"idem_{uuid4().hex}"
        if operation in {"UPSERT", "DELETE", "LOCK", "UNLOCK"}
        else None,
        transaction={"mode": "LOCAL"},
    )
    return request


@pytest.mark.parametrize(
    "field",
    [
        "command",
        "raw_command",
        "redis_command",
        "eval",
        "lua",
        "keys",
        "scan",
        "flushdb",
        "connection_string",
        "redis_url",
    ],
)
async def test_redis_raw_command_surfaces_are_rejected(client: AsyncClient, field: str) -> None:
    request = redis_request({"logical_key": f"k_{uuid4().hex}", "value": {"ok": True}, field: "x"})
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_redis_full_physical_key_is_rejected(client: AsyncClient) -> None:
    request = redis_request({"logical_key": "dcs:tenant_demo:demo:cache:forbidden", "value": {}})
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


async def test_redis_biz_domain_scope_mismatch_is_rejected(client: AsyncClient) -> None:
    request = redis_request({"logical_key": f"k_{uuid4().hex}", "value": {}})
    scoped = deepcopy(request)
    scoped["auth_context"]["biz_domain"] = "finance"  # type: ignore[index]
    response = await client.post("/data/dispatch", json=scoped)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"
