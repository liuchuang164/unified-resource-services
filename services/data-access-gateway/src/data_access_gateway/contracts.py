from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(pattern=r"^1\.0$")
    request_id: str = Field(min_length=6, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    trace_id: str = Field(min_length=6, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    session_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    task_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    tool_call_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    tenant_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    biz_domain: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    tool_name: str = Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_.-]+$")
    action: str = Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_]+$")
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=6, max_length=256)
    timeout_ms: int = Field(default=10_000, ge=100, le=60_000)


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    details: list[dict[str, Any]] = Field(default_factory=list)
    incident_id: str | None = None


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0"
    request_id: str
    trace_id: str
    success: bool
    tool_name: str
    action: str
    data: Any | None = None
    error: ToolError | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
