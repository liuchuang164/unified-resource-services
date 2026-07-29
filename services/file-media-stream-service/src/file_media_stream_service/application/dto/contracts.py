from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    biz_domain: str = Field(min_length=1, max_length=64)
    caller_type: Literal["agent", "service", "user", "platform"]
    caller_id: str = Field(min_length=1, max_length=128)
    agent_id: str | None = None
    tool_call_id: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    policy_version: str = "v1"
    idempotency_key: str | None = Field(default=None, max_length=128)
    nonce: str | None = Field(default=None, max_length=128)
    capability_token: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_agent_context(self) -> "RequestContext":
        if self.caller_type == "agent" and (not self.agent_id or not self.tool_call_id):
            raise ValueError("agent_id and tool_call_id are required for agent calls")
        return self


class UnifiedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str
    operation: str = Field(min_length=1)
    context: RequestContext
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class UnifiedResponse(BaseModel):
    request_id: str
    trace_id: str
    success: bool
    data: dict[str, Any] | None
    error: ErrorDetail | None

    @model_validator(mode="after")
    def validate_shape(self) -> "UnifiedResponse":
        if self.success == (self.error is not None) or self.success == (self.data is None):
            raise ValueError("success responses require data; failures require error")
        return self


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    context: RequestContext
    params: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    tool_name: str
    tool_call_id: str
    response: UnifiedResponse
