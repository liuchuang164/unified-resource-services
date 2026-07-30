from __future__ import annotations

import base64
import os
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from data_control_service.api.dependencies import (
    get_control_database_manager,
    get_data_control_service,
    get_minio_manager,
    get_redis_manager,
    get_settings,
    get_target_postgresql_manager,
)
from data_control_service.app import create_app

pytestmark = pytest.mark.minio


def _minio_available() -> bool:
    return bool(os.getenv("MINIO_ENDPOINT") and os.getenv("CONTROL_DATABASE_URL"))


def _request(operation: str, data: dict[str, Any], idem: str | None = None) -> dict[str, Any]:
    key = uuid4().hex
    return {
        "contract_version": "1.0",
        "request_id": f"req_MINIO_{key}",
        "trace_id": f"trace_MINIO_{key}",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": operation,
        "resource": {
            "target": "MINIO",
            "type": "OBJECT_ASSET",
            "name": "asset",
            "resource_id": data.get("logical_object_id"),
        },
        "payload": {"data": data, "query": {}, "options": {}},
        "idempotency_key": idem,
        "transaction": {"mode": "LOCAL"},
        "timeout_ms": 10000,
        "metadata": {"caller_service": "test"},
    }


async def _client() -> AsyncClient:
    get_settings.cache_clear()
    get_control_database_manager.cache_clear()
    get_target_postgresql_manager.cache_clear()
    get_redis_manager.cache_clear()
    get_minio_manager.cache_clear()
    get_data_control_service.cache_clear()
    return AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        headers={
            "x-dev-subject-id": "svc_demo",
            "x-dev-tenant-id": "tenant_demo",
            "x-dev-biz-domains": "demo",
            "x-dev-permissions": "data:asset:read,data:asset:write,data:high-risk:execute",
        },
    )


def _txt_payload(filename: str = "hello.txt") -> dict[str, Any]:
    content = b"hello minio\n"
    return {
        "filename": filename,
        "content_type": "text/plain",
        "size_bytes": len(content),
        "content_base64": base64.b64encode(content).decode(),
    }


@pytest.mark.skipif(not _minio_available(), reason="real MinIO and control PostgreSQL required")
async def test_minio_create_get_exists_list_presign_delete_over_dispatch() -> None:
    async with await _client() as client:
        create = await client.post(
            "/data/dispatch", json=_request("CREATE", _txt_payload(), f"idem_{uuid4().hex}")
        )
        assert create.status_code == 200
        data = create.json()["data"]
        assert "object_key" not in data
        logical_object_id = data["logical_object_id"]
        get = await client.post(
            "/data/dispatch", json=_request("GET", {"logical_object_id": logical_object_id})
        )
        exists = await client.post(
            "/data/dispatch", json=_request("EXISTS", {"logical_object_id": logical_object_id})
        )
        listing = await client.post("/data/dispatch", json=_request("LIST", {}))
        presign = await client.post(
            "/data/dispatch",
            json=_request("PRESIGN_DOWNLOAD", {"logical_object_id": logical_object_id}),
        )
        delete = await client.post(
            "/data/dispatch",
            json=_request(
                "DELETE", {"logical_object_id": logical_object_id}, f"idem_{uuid4().hex}"
            ),
        )
        missing = await client.post(
            "/data/dispatch", json=_request("EXISTS", {"logical_object_id": logical_object_id})
        )

    assert get.json()["data"]["checksum_sha256"] == data["checksum_sha256"]
    assert exists.json()["data"]["exists"] is True
    assert any(item["logical_object_id"] == logical_object_id for item in listing.json()["data"])
    assert "download_url" in presign.json()["data"]
    assert "object_key" not in presign.text
    assert delete.json()["data"]["deleted"] is True
    assert missing.json()["data"]["exists"] is False


@pytest.mark.skipif(not _minio_available(), reason="real MinIO and control PostgreSQL required")
async def test_minio_presigned_upload_complete_and_idempotency() -> None:
    async with await _client() as client:
        presigned = await client.post(
            "/data/dispatch",
            json=_request(
                "PRESIGN_UPLOAD",
                {"filename": "pending.txt", "content_type": "text/plain", "size_bytes": 12},
                f"idem_{uuid4().hex}",
            ),
        )
        assert presigned.status_code == 200
        upload_url = presigned.json()["data"]["upload_url"]
        logical_object_id = presigned.json()["data"]["logical_object_id"]
        async with AsyncClient(timeout=30.0) as raw_client:
            put = await raw_client.put(
                upload_url, content=b"hello minio\n", headers={"Content-Type": "text/plain"}
            )
        complete = await client.post(
            "/data/dispatch",
            json=_request(
                "UPLOAD_COMPLETE", {"logical_object_id": logical_object_id}, f"idem_{uuid4().hex}"
            ),
        )
        replay_payload = _request(
            "DELETE", {"logical_object_id": logical_object_id}, "idem_replay_minio"
        )
        first_delete = await client.post("/data/dispatch", json=replay_payload)
        second_replay_payload = deepcopy(replay_payload)
        replay_key = uuid4().hex
        second_replay_payload["request_id"] = f"req_MINIO_REPLAY_{replay_key}"
        second_replay_payload["trace_id"] = f"trace_MINIO_REPLAY_{replay_key}"
        second_delete = await client.post("/data/dispatch", json=second_replay_payload)

    assert put.status_code in {200, 204}
    assert complete.status_code == 200
    assert complete.json()["data"]["status"] == "AVAILABLE"
    assert first_delete.status_code == 200
    assert second_delete.status_code == 200
    assert second_delete.json()["meta"]["idempotency_replayed"] is True
