from copy import deepcopy
from typing import Any

from httpx import AsyncClient


async def test_tools_are_discoverable_for_authorized_agent(
    client: AsyncClient,
    token: str,
) -> None:
    response = await client.get(
        "/dag/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    tool = response.json()["tools"][0]
    assert tool["name"] == "minio_file_access"
    assert "create_upload_url" in tool["actions"]


async def test_tool_schema_contains_action_parameter_schema(
    client: AsyncClient,
    token: str,
) -> None:
    response = await client.get(
        "/dag/tools/minio_file_access/schema",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    action = next(item for item in response.json()["actions"] if item["name"] == "upload_inline")
    assert action["operation"] == "CREATE"
    assert action["params_schema"]["additionalProperties"] is False


async def test_execute_converts_and_forwards_capability_token(
    client: AsyncClient,
    token: str,
    base_request: dict[str, Any],
    fake_client: Any,
) -> None:
    response = await client.post(
        "/dag/tools/execute",
        json=base_request,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    forwarded = fake_client.requests[0]
    assert forwarded["source"] == "DATA_ACCESS_GATEWAY"
    assert forwarded["auth_context"]["actor"] == {"id": "agent_demo", "type": "AGENT"}
    assert forwarded["resource"]["target"] == "MINIO"


async def test_execute_rejects_scope_mismatch(
    client: AsyncClient,
    token: str,
    base_request: dict[str, Any],
) -> None:
    request = deepcopy(base_request)
    request["tenant_id"] = "tenant_other"
    response = await client.post(
        "/dag/tools/execute",
        json=request,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TOOL_SCOPE_MISMATCH"


async def test_execute_rejects_physical_minio_fields(
    client: AsyncClient,
    token: str,
    base_request: dict[str, Any],
) -> None:
    request = deepcopy(base_request)
    request["params"]["bucket"] = "private-bucket"
    response = await client.post(
        "/dag/tools/execute",
        json=request,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TOOL_PARAMS_INVALID"
    assert "private-bucket" not in response.text
