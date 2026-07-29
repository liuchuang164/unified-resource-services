from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_control_service.contracts.enums import (
    WRITE_OPERATIONS,
    DataClass,
    DataTarget,
    Operation,
    Source,
    SubjectType,
    TransactionMode,
)


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    type: SubjectType


class AuthContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    biz_domain: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    actor: Actor


class ResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: DataTarget
    type: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)
    data_class: DataClass | None = None


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_raw_query_surfaces(self) -> "Payload":
        forbidden = {
            "sql",
            "raw_sql",
            "cypher",
            "raw_cypher",
            "redis_command",
            "command",
            "connection_string",
            "bucket",
            "object_key",
            "path",
        }
        for section_name, section in (
            ("data", self.data),
            ("query", self.query),
            ("options", self.options),
        ):
            lower_keys = {key.lower() for key in section}
            if lower_keys & forbidden:
                raise ValueError(f"{section_name} contains forbidden raw access fields")
        return self


class TransactionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TransactionMode = TransactionMode.LOCAL
    isolation: str | None = Field(default=None, max_length=64)


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    request_id: str = Field(min_length=6, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    trace_id: str | None = Field(default=None, min_length=6, max_length=128)
    source: Source
    auth_context: AuthContext
    operation: Operation
    resource: ResourceDescriptor
    payload: Payload
    idempotency_key: str | None = Field(default=None, min_length=6, max_length=256)
    transaction: TransactionOptions | None = None
    timeout_ms: int | None = Field(default=None, ge=100, le=60_000)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=32)

    @field_validator("contract_version")
    @classmethod
    def version_must_be_frozen_contract(cls, value: str) -> str:
        if value != "1.0":
            raise ValueError("contract version is unsupported")
        return value

    @model_validator(mode="after")
    def write_operations_require_idempotency_key(self) -> "DataRequest":
        if self.operation in WRITE_OPERATIONS and not self.idempotency_key:
            raise ValueError("write operation requires idempotency_key")
        return self

    @property
    def is_write(self) -> bool:
        return self.operation in WRITE_OPERATIONS
