from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TrustedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    biz_domain: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    caller_type: Literal["AGENT_TOOL", "BUSINESS_SERVICE"]
    caller_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=128)
    roles: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    source: Literal["headers", "legacy_body"] = "headers"
