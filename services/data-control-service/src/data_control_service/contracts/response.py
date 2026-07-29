from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = None
    limit: int = Field(default=50, ge=1)
    has_more: bool = False


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    retryable: bool
    details: list[dict[str, Any]] = Field(default_factory=list)
    incident_id: str | None = None


class DataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0"
    request_id: str
    trace_id: str
    success: bool
    code: str
    message: str
    data: Any | None = None
    page: PageInfo | None = None
    error: ErrorBody | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
