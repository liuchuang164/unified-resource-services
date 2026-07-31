from copy import deepcopy

import pytest
from pydantic import ValidationError

from data_access_gateway.auth import CapabilityPrincipal
from data_access_gateway.contracts import ToolExecuteRequest
from data_access_gateway.errors import GatewayError
from data_access_gateway.minio_tool import MINIO_TOOL, to_data_request
from data_access_gateway.registry import ToolRegistry


def _principal() -> CapabilityPrincipal:
    return CapabilityPrincipal(
        agent_id="agent_demo",
        tenant_id="tenant_demo",
        biz_domain="demo",
        session_id="session_demo",
        task_id="task_demo",
        roles=("AGENT",),
        permissions=("data:object:read", "data:object:write"),
        allowed_tools=("minio_file_access",),
        allowed_actions=tuple(f"minio_file_access:{action.name}" for action in MINIO_TOOL.actions),
    )


def test_registry_rejects_unknown_action() -> None:
    registry = ToolRegistry([MINIO_TOOL])
    with pytest.raises(GatewayError) as exc_info:
        registry.action("minio_file_access", "raw_object_access")
    assert exc_info.value.code == "TOOL_ACTION_NOT_SUPPORTED"


@pytest.mark.parametrize(
    ("action_name", "operation"),
    [
        ("list_objects", "LIST"),
        ("get_object_metadata", "GET"),
        ("object_exists", "EXISTS"),
        ("upload_inline", "CREATE"),
        ("create_upload_url", "PRESIGN_UPLOAD"),
        ("complete_upload", "UPLOAD_COMPLETE"),
        ("create_download_url", "PRESIGN_DOWNLOAD"),
        ("delete_object", "DELETE"),
    ],
)
def test_all_minio_actions_have_stable_operation_mapping(
    base_request: dict[str, object],
    action_name: str,
    operation: str,
) -> None:
    registry = ToolRegistry([MINIO_TOOL])
    _, action = registry.action("minio_file_access", action_name)
    assert action.operation == operation


def test_write_key_is_generated_deterministically(base_request: dict[str, object]) -> None:
    request_body = deepcopy(base_request)
    request_body["action"] = "delete_object"
    request_body["params"] = {"logical_object_id": "obj_demo", "reason": "manual verification"}
    request = ToolExecuteRequest.model_validate(request_body)
    _, action = ToolRegistry([MINIO_TOOL]).action(request.tool_name, request.action)
    params = action.params_model.model_validate(request.params)
    first = to_data_request(request, _principal(), action, params)
    second = to_data_request(request, _principal(), action, params)
    assert first["idempotency_key"] == second["idempotency_key"]
    assert str(first["idempotency_key"]).startswith("dag_")


def test_read_action_does_not_create_idempotency_key(base_request: dict[str, object]) -> None:
    request = ToolExecuteRequest.model_validate(base_request)
    _, action = ToolRegistry([MINIO_TOOL]).action(request.tool_name, request.action)
    params = action.params_model.model_validate(request.params)
    converted = to_data_request(request, _principal(), action, params)
    assert converted["idempotency_key"] is None


@pytest.mark.parametrize(
    "forbidden",
    ["bucket", "object_key", "endpoint", "access_key", "secret_key", "local_path"],
)
def test_physical_storage_fields_are_rejected(
    base_request: dict[str, object],
    forbidden: str,
) -> None:
    request_body = deepcopy(base_request)
    request_body["params"] = {
        "logical_object_id": "obj_demo",
        forbidden: "forbidden",
    }
    request = ToolExecuteRequest.model_validate(request_body)
    _, action = ToolRegistry([MINIO_TOOL]).action(request.tool_name, request.action)
    with pytest.raises(ValidationError):
        action.params_model.model_validate(request.params)


def test_nested_physical_storage_fields_are_rejected(
    base_request: dict[str, object],
) -> None:
    request_body = deepcopy(base_request)
    request_body["action"] = "upload_inline"
    request_body["params"] = {
        "filename": "safe.txt",
        "content_type": "text/plain",
        "size_bytes": 4,
        "content_text": "safe",
        "metadata": {"object_key": "tenant/other/private"},
    }
    request = ToolExecuteRequest.model_validate(request_body)
    _, action = ToolRegistry([MINIO_TOOL]).action(request.tool_name, request.action)
    with pytest.raises(ValidationError):
        action.params_model.model_validate(request.params)
