from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from external_access_service.application.services.unified_entry import UnifiedExternalEntry
from external_access_service.domain.errors import InvalidRequest, OperationNotFound
from external_access_service.domain.models import (
    AuthContext,
    BizContext,
    DispatchPolicy,
    ExternalDispatchRequest,
    ExternalDispatchResponse,
    ProviderCode,
    ProviderRef,
    RequestSource,
)
from external_access_service.domain.operations import OperationRegistry

TOOL_NAME = "ali_farui"
ACTION_OPERATION = {
    "legal_consult": "ALI_FARUI_LEGAL_CONSULT",
    "law_search": "ALI_FARUI_LAW_SEARCH",
    "case_search": "ALI_FARUI_CASE_SEARCH",
    "legal_research_full": "ALI_FARUI_LEGAL_RESEARCH_FULL",
}


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    biz_domain: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    action: str = Field(min_length=1)
    capability_token: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    user_id: str = "agent-user"
    session_id: str | None = None
    task_id: str | None = None

    @model_validator(mode="after")
    def reject_scope_in_input(self) -> "ToolExecuteRequest":
        if "tenant_id" in self.input or "biz_domain" in self.input:
            raise ValueError("tenant_id and biz_domain are trusted context fields")
        return self


class ToolResponse(BaseModel):
    tool_name: str
    action: str
    tool_call_id: str
    response: ExternalDispatchResponse


class ToolGateway:
    def __init__(self, entry: UnifiedExternalEntry, operations: OperationRegistry) -> None:
        self.entry = entry
        self.operations = operations

    def list_tools(self, tenant_id: str, biz_domain: str) -> list[dict[str, Any]]:
        if not tenant_id or biz_domain != "LEGAL":
            return []
        return [
            {
                "tool_name": TOOL_NAME,
                "provider": ProviderCode.ALI_FARUI.value,
                "actions": list(ACTION_OPERATION),
            }
        ]

    def schema(self, tool_name: str) -> dict[str, Any]:
        if tool_name != TOOL_NAME:
            raise OperationNotFound("Tool is not registered")
        return {
            "tool_name": TOOL_NAME,
            "actions": {
                action: self.operations.get(operation).payload_schema
                for action, operation in ACTION_OPERATION.items()
            },
        }

    async def execute(self, request: ToolExecuteRequest) -> ToolResponse:
        if request.tool_name != TOOL_NAME:
            raise OperationNotFound("Tool is not registered")
        operation = ACTION_OPERATION.get(request.action)
        if operation is None:
            raise InvalidRequest("Tool action is not registered")
        dispatch_request = ExternalDispatchRequest(
            request_id=request.request_id,
            trace_id=request.trace_id,
            request_source=RequestSource.AGENT_TOOL,
            auth_context=AuthContext(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                roles=("AGENT",),
            ),
            biz_context=BizContext(biz_domain=request.biz_domain, biz_scene="LEGAL_RESEARCH"),
            operation=operation,
            provider=ProviderRef(provider_code=ProviderCode.ALI_FARUI, capability="LEGAL_RESEARCH"),
            payload=request.input,
            policy=DispatchPolicy(),
            caller_id=request.agent_id,
            agent_id=request.agent_id,
            tool_call_id=request.tool_call_id,
        )
        return ToolResponse(
            tool_name=request.tool_name,
            action=request.action,
            tool_call_id=request.tool_call_id,
            response=await self.entry.dispatch(dispatch_request),
        )
