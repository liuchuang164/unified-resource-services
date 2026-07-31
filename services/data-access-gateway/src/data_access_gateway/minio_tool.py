import base64
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_access_gateway.auth import CapabilityPrincipal
from data_access_gateway.contracts import ToolExecuteRequest
from data_access_gateway.registry import ToolAction, ToolDefinition

FORBIDDEN_STORAGE_FIELDS = {
    "bucket",
    "bucket_name",
    "object_key",
    "endpoint",
    "access_key",
    "secret_key",
    "local_path",
    "filesystem_path",
    "physical_path",
    "minio_url",
    "s3_url",
}


class StrictParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_physical_storage_fields(self) -> "StrictParams":
        if _contains_forbidden_field(self.model_dump()):
            raise ValueError("physical storage fields are not allowed")
        return self


class ListObjectsParams(StrictParams):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1024)


class ObjectReferenceParams(StrictParams):
    logical_object_id: str = Field(min_length=3, max_length=256)


class UploadInlineParams(StrictParams):
    logical_object_id: str | None = Field(default=None, min_length=3, max_length=256)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(ge=0)
    content_text: str | None = Field(default=None, max_length=1_000_000)
    content_base64: str | None = Field(default=None, max_length=1_500_000)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def exactly_one_content_source(self) -> "UploadInlineParams":
        if (self.content_text is None) == (self.content_base64 is None):
            raise ValueError("exactly one of content_text or content_base64 is required")
        if self.content_base64 is not None:
            try:
                base64.b64decode(self.content_base64, validate=True)
            except ValueError as exc:
                raise ValueError("content_base64 is invalid") from exc
        return self


class CreateUploadUrlParams(StrictParams):
    logical_object_id: str | None = Field(default=None, min_length=3, max_length=256)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(gt=0)
    ttl_seconds: int | None = Field(default=None, ge=1, le=3600)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=16)


class CompleteUploadParams(ObjectReferenceParams):
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class CreateDownloadUrlParams(ObjectReferenceParams):
    ttl_seconds: int | None = Field(default=None, ge=1, le=3600)


class DeleteObjectParams(ObjectReferenceParams):
    reason: str = Field(min_length=3, max_length=500)


MINIO_TOOL = ToolDefinition(
    name="minio_file_access",
    version="1.0",
    description="Controlled logical object access through the data control service",
    target="MINIO",
    resource_type="OBJECT_ASSET",
    resource_name="asset",
    actions=(
        ToolAction("list_objects", "LIST", ListObjectsParams, False),
        ToolAction("get_object_metadata", "GET", ObjectReferenceParams, False),
        ToolAction("object_exists", "EXISTS", ObjectReferenceParams, False),
        ToolAction("upload_inline", "CREATE", UploadInlineParams, True),
        ToolAction("create_upload_url", "PRESIGN_UPLOAD", CreateUploadUrlParams, True),
        ToolAction("complete_upload", "UPLOAD_COMPLETE", CompleteUploadParams, True),
        ToolAction("create_download_url", "PRESIGN_DOWNLOAD", CreateDownloadUrlParams, False),
        ToolAction("delete_object", "DELETE", DeleteObjectParams, True, True),
    ),
)


def to_data_request(
    request: ToolExecuteRequest,
    principal: CapabilityPrincipal,
    action: ToolAction,
    params: BaseModel,
) -> dict[str, Any]:
    values = params.model_dump(exclude_none=True)
    data: dict[str, Any] = {}
    options: dict[str, Any] = {}
    if action.name == "list_objects":
        options = values
    elif action.name in {"create_upload_url", "create_download_url"}:
        ttl = values.pop("ttl_seconds", None)
        data = values
        if ttl is not None:
            options["presigned_url_ttl_seconds"] = ttl
    else:
        data = values
    resource_id = data.get("logical_object_id")
    idempotency_key = request.idempotency_key
    if action.write and not idempotency_key:
        idempotency_key = _idempotency_key(request, principal)
    return {
        "contract_version": "1.0",
        "request_id": request.request_id,
        "trace_id": request.trace_id,
        "source": "DATA_ACCESS_GATEWAY",
        "auth_context": {
            "tenant_id": principal.tenant_id,
            "biz_domain": principal.biz_domain,
            "actor": {"id": principal.agent_id, "type": "AGENT"},
        },
        "operation": action.operation,
        "resource": {
            "target": MINIO_TOOL.target,
            "type": MINIO_TOOL.resource_type,
            "name": MINIO_TOOL.resource_name,
            "resource_id": resource_id,
            "data_class": "OBJECT",
        },
        "payload": {"data": data, "query": {}, "options": options},
        "idempotency_key": idempotency_key,
        "transaction": {"mode": "LOCAL"},
        "timeout_ms": request.timeout_ms,
        "metadata": {
            "caller_service": "data-access-gateway",
            "tool_name": request.tool_name,
            "tool_action": request.action,
            "session_id": request.session_id,
            "task_id": request.task_id,
            "tool_call_id": request.tool_call_id,
        },
    }


def _idempotency_key(request: ToolExecuteRequest, principal: CapabilityPrincipal) -> str:
    material = "|".join(
        (
            principal.tenant_id,
            principal.biz_domain,
            principal.agent_id,
            request.session_id,
            request.task_id,
            request.tool_call_id,
            request.tool_name,
            request.action,
        )
    )
    return f"dag_{sha256(material.encode()).hexdigest()}"


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in FORBIDDEN_STORAGE_FIELDS or _contains_forbidden_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False
