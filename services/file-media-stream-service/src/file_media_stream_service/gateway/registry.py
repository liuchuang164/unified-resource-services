from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from file_media_stream_service.application.dto.contracts import (
    ToolExecuteRequest,
    ToolResponse,
    UnifiedRequest,
)
from file_media_stream_service.entry.payloads import PAYLOAD_MODELS
from file_media_stream_service.entry.service import UnifiedEntry

TOOL_OPERATIONS: dict[str, str | None] = {
    "file_media.list_tools": None,
    "file_media.get_tool_schema": None,
    "file.initialize_upload": "file.initialize_upload",
    "file.create_upload_session": "file.initialize_upload",
    "file.complete_upload": "file.complete_upload",
    "file.abort_upload": "file.abort_upload",
    "file.create_download_url": "file.create_download_url",
    "file.read_range": "file.read_range",
    "file.get_metadata": "file.get_metadata",
    "file.delete_file": "file.delete_file",
    "file.get_resource": "file.get_resource",
    "media.create_stream_session": "media.create_stream_session",
    "media.get_stream_session": "media.get_stream_session",
    "media.close_stream_session": "media.close_stream_session",
    "media.submit_processing_job": "media.submit_processing_job",
    "media.get_processing_job": "media.get_processing_job",
}

_METADATA_SCHEMAS: dict[str, dict[str, Any]] = {
    "file_media.list_tools": {"type": "object", "properties": {}, "additionalProperties": False},
    "file_media.get_tool_schema": {
        "type": "object",
        "properties": {"tool_name": {"type": "string"}},
        "required": ["tool_name"],
        "additionalProperties": False,
    },
}
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    **_METADATA_SCHEMAS,
    **{operation: model.model_json_schema() for operation, model in PAYLOAD_MODELS.items()},
}
TOOL_SCHEMAS["file.create_upload_session"] = PAYLOAD_MODELS[
    "file.initialize_upload"
].model_json_schema()


class ToolNotExecutable(ValueError):
    """Raised when a discovery-only metadata tool is sent to the execution endpoint."""


class ToolGateway:
    def __init__(self, unified_entry: UnifiedEntry) -> None:
        self.unified_entry = unified_entry

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, "schema": deepcopy(TOOL_SCHEMAS[name])} for name in TOOL_OPERATIONS]

    def get_schema(self, tool_name: str) -> dict[str, Any] | None:
        schema = TOOL_SCHEMAS.get(tool_name)
        return deepcopy(schema) if schema else None

    async def execute(self, request: ToolExecuteRequest) -> ToolResponse:
        operation = TOOL_OPERATIONS.get(request.tool_name)
        if operation is None:
            raise ToolNotExecutable("Metadata tools are exposed through GET endpoints")
        try:
            params = PAYLOAD_MODELS[operation].model_validate(request.params).model_dump()
        except ValidationError:
            # Unified Entry repeats validation so malformed Tool calls receive its audited,
            # stable error response instead of a framework exception.
            params = request.params
        unified = await self.unified_entry.execute(
            UnifiedRequest(
                api_version="v1",
                operation=operation,
                context=request.context,
                payload=params,
            ),
            source="gateway",
        )
        return ToolResponse(
            tool_name=request.tool_name,
            tool_call_id=request.context.tool_call_id or "",
            response=unified,
        )
