from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderCode(StrEnum):
    ALI_FARUI = "ALI_FARUI"
    MOCK_LEGAL_PROVIDER = "MOCK_LEGAL_PROVIDER"


class RequestSource(StrEnum):
    AGENT_TOOL = "AGENT_TOOL"
    BUSINESS_SERVICE = "BUSINESS_SERVICE"


class DispatchStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AuthContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = ()


class BizContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    biz_domain: str = Field(min_length=1, max_length=64)
    biz_scene: str | None = Field(default=None, max_length=128)


class ProviderRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_code: ProviderCode
    capability: str = Field(min_length=1, max_length=128)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    max_attempts: int = Field(default=2, ge=1, le=3)


class DispatchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_ms: int = Field(default=30_000, ge=100, le=60_000)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    max_cost_amount: float = Field(default=5, ge=0)
    cost_unit: str = "CNY"


class ExternalDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    request_source: RequestSource
    auth_context: AuthContext
    biz_context: BizContext
    operation: str = Field(min_length=1, max_length=128)
    provider: ProviderRef
    payload: dict[str, Any] = Field(default_factory=dict)
    policy: DispatchPolicy = Field(default_factory=DispatchPolicy)
    idempotency_key: str | None = Field(default=None, max_length=128)
    caller_id: str | None = Field(default=None, max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_agent_context(self) -> "ExternalDispatchRequest":
        if self.request_source == RequestSource.AGENT_TOOL and (
            not self.agent_id or not self.tool_call_id
        ):
            raise ValueError("agent_id and tool_call_id are required for Agent Tool calls")
        return self


class Usage(BaseModel):
    request_count: int = 1
    input_units: int = 0
    output_units: int = 0
    estimated_cost: float = 0


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ExternalDispatchResponse(BaseModel):
    request_id: str
    trace_id: str
    tenant_id: str
    biz_domain: str
    operation: str
    provider: ProviderCode
    status: DispatchStatus
    data: dict[str, Any] | None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int
    provider_request_id: str | None = None
    error: ErrorDetail | None

    @model_validator(mode="after")
    def validate_shape(self) -> "ExternalDispatchResponse":
        if self.status == DispatchStatus.SUCCEEDED and self.error is not None:
            raise ValueError("success response cannot include error")
        if self.status == DispatchStatus.FAILED and self.error is None:
            raise ValueError("failed response must include error")
        return self


class ProviderCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_ref: str
    version: str
    api_key: str
    api_secret: str
    token: str | None = None


class ProviderResult(BaseModel):
    data: dict[str, Any]
    usage: Usage = Field(default_factory=Usage)
    provider_request_id: str | None = None
