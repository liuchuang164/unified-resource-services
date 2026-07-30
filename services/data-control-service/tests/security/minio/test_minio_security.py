from __future__ import annotations

import base64
from copy import deepcopy
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.test_dispatch_pipeline import base_request

pytestmark = pytest.mark.minio


def _minio_request(payload_data: dict[str, object]) -> dict[str, object]:
    req = base_request(
        operation="CREATE",
        resource={
            "target": "MINIO",
            "type": "OBJECT_ASSET",
            "name": "asset",
            "resource_id": None,
        },
        payload={"data": payload_data, "query": {}, "options": {}},
        idempotency_key=f"idem_MINIO_SECURITY_{uuid4().hex}",
    )
    return req


def _valid_payload() -> dict[str, object]:
    content = b"safe text\n"
    return {
        "filename": "safe.txt",
        "content_type": "text/plain",
        "size_bytes": len(content),
        "content_base64": base64.b64encode(content).decode(),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bucket", "dcs-objects"),
        ("object_key", "tenant/other/key"),
        ("endpoint", "localhost:9000"),
        ("access_key", "test"),
        ("secret_key", "test"),
        ("physical_path", "tenant/demo"),
        ("local_path", "/private/tenant/file.txt"),
        ("filesystem_path", "C:\\tmp\\file.txt"),
    ],
)
async def test_minio_forbidden_storage_fields_rejected(
    client: AsyncClient, field: str, value: str
) -> None:
    payload = _valid_payload()
    payload[field] = value
    response = await client.post("/data/dispatch", json=_minio_request(payload))
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "filename", ["../secret.txt", "..\\secret.txt", "/etc/passwd", "C:\\tmp\\x.txt", "file://x.txt"]
)
async def test_minio_path_traversal_rejected(client: AsyncClient, filename: str) -> None:
    payload = _valid_payload()
    payload["filename"] = filename
    response = await client.post("/data/dispatch", json=_minio_request(payload))
    assert response.status_code == 400
    assert response.json()["code"] in {"OBJECT_PATH_INVALID", "REQUEST_SCHEMA_INVALID"}


async def test_minio_content_type_extension_and_magic_rejected(client: AsyncClient) -> None:
    payload = _valid_payload()
    payload["filename"] = "bad.pdf"
    payload["content_type"] = "application/pdf"
    response = await client.post("/data/dispatch", json=_minio_request(payload))
    assert response.status_code in {400, 422}
    assert response.json()["code"] in {"CONTENT_TYPE_NOT_ALLOWED", "REQUEST_SCHEMA_INVALID"}


async def test_minio_cross_tenant_isolation(client: AsyncClient) -> None:
    create = await client.post("/data/dispatch", json=_minio_request(_valid_payload()))
    object_id = create.json()["data"]["logical_object_id"]
    request = deepcopy(_minio_request({"logical_object_id": object_id}))
    request["operation"] = "GET"
    request["idempotency_key"] = None
    request["auth_context"]["tenant_id"] = "tenant_other"
    response = await client.post("/data/dispatch", json=request)
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"
