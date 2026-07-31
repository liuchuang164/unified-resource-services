from httpx import AsyncClient


async def test_operation_discovery_exposes_logical_capabilities(client: AsyncClient) -> None:
    response = await client.get("/data/operations", params={"biz_domain": "demo"})
    assert response.status_code == 200
    body = response.json()
    minio = next(item for item in body["operations"] if item["target"] == "MINIO")
    assert "PRESIGN_UPLOAD" in minio["operations"]
    assert "bucket" not in response.text.lower()
    assert "object_key" not in response.text.lower()


async def test_operation_schema_requires_allowed_business_domain(client: AsyncClient) -> None:
    response = await client.get(
        "/data/operations/GET/schema",
        params={"biz_domain": "other"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_SCOPE_MISMATCH"


async def test_operation_schema_is_generated_from_data_request(client: AsyncClient) -> None:
    response = await client.get(
        "/data/operations/PRESIGN_UPLOAD/schema",
        params={"biz_domain": "demo"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "PRESIGN_UPLOAD"
    assert "request_schema" in body
