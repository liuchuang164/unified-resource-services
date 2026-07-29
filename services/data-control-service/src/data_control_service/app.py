from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "data-control-service"
    contract_version: str = "1.0"
    default_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)


class Operation(StrEnum):
    GET = "GET"
    LIST = "LIST"
    SEARCH = "SEARCH"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    UPSERT = "UPSERT"
    DELETE = "DELETE"
    BATCH = "BATCH"
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"


class DataTarget(StrEnum):
    POSTGRESQL = "POSTGRESQL"
    MINIO = "MINIO"
    REDIS = "REDIS"
    NEO4J = "NEO4J"
    MILVUS = "MILVUS"
    TIMESCALEDB = "TIMESCALEDB"


WRITE_OPERATIONS = {
    Operation.CREATE,
    Operation.UPDATE,
    Operation.UPSERT,
    Operation.DELETE,
    Operation.BATCH,
    Operation.LOCK,
    Operation.UNLOCK,
}

ERRORS = {
    "REQUEST_SCHEMA_INVALID": (400, False, "CONTRACT", "request schema is invalid"),
    "IDEMPOTENCY_KEY_REQUIRED": (400, False, "IDEMPOTENCY", "idempotency key is required"),
    "IDEMPOTENCY_IN_PROGRESS": (409, True, "IDEMPOTENCY", "idempotent request is still processing"),
    "IDEMPOTENCY_KEY_CONFLICT": (409, False, "IDEMPOTENCY", "idempotency key conflicts with a different request"),
    "AUTH_REQUIRED": (401, False, "AUTHENTICATION", "authentication is required"),
    "AUTH_SCOPE_MISMATCH": (403, False, "AUTHORIZATION", "request scope is not permitted"),
    "PERMISSION_DENIED": (403, False, "AUTHORIZATION", "permission denied"),
    "RESOURCE_TYPE_UNKNOWN": (422, False, "CONTRACT", "resource type is unknown"),
    "OPERATION_NOT_SUPPORTED": (422, False, "CONTRACT", "operation is not supported"),
    "TRANSACTION_NOT_SUPPORTED": (422, False, "TRANSACTION", "transaction is not supported"),
    "RESOURCE_NOT_FOUND": (404, False, "DATA", "resource was not found"),
    "ADAPTER_NOT_REGISTERED": (500, False, "ADAPTER", "adapter is not registered"),
    "INTERNAL_ERROR": (500, True, "INTERNAL", "internal error"),
    "OK": (200, False, "SUCCESS", "success"),
}


class DataControlError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        http_status, retryable, category, default_message = ERRORS[code]
        self.http_status = http_status
        self.retryable = retryable
        self.category = category
        self.message = message or default_message
        self.incident_id = f"inc_{uuid4().hex}" if http_status >= 500 else None
        super().__init__(self.message)


class AuthContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    subject_type: str = Field(min_length=2, max_length=32)
    tenant_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    biz_domain: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    roles: list[str] = Field(default_factory=list, max_length=32)
    permissions: list[str] = Field(default_factory=list, max_length=128)


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: DataTarget
    type: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)
    data_class: str | None = None


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_raw_access(self) -> Payload:
        forbidden = {"sql", "raw_sql", "cypher", "raw_cypher", "redis_command", "command", "connection_string", "bucket", "object_key", "path"}
        for section in (self.data, self.query, self.options):
            if {key.lower() for key in section} & forbidden:
                raise ValueError("payload contains forbidden raw access fields")
        return self


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "LOCAL"
    isolation: str | None = None


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: str
    request_id: str = Field(min_length=6, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    trace_id: str | None = Field(default=None, min_length=6, max_length=128)
    source: str = Field(pattern=r"^(BUSINESS_SERVICE|ONTOLOGY_SERVICE|DATA_ACCESS_GATEWAY|INTERNAL_JOB)$")
    auth_context: AuthContext
    operation: Operation
    resource: Resource
    payload: Payload
    idempotency_key: str | None = Field(default=None, min_length=6, max_length=256)
    transaction: Transaction | None = None
    timeout_ms: int | None = Field(default=None, ge=100, le=60_000)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_contract_and_idempotency(self) -> DataRequest:
        if self.contract_version != "1.0":
            raise ValueError("contract version is unsupported")
        if self.operation in WRITE_OPERATIONS and not self.idempotency_key:
            raise ValueError("write operation requires idempotency_key")
        return self


class DataResponse(BaseModel):
    contract_version: str = "1.0"
    request_id: str
    trace_id: str
    success: bool
    code: str
    message: str
    data: Any | None = None
    page: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ResourcePolicy:
    target: DataTarget
    resource_type: str
    name: str
    operations: frozenset[Operation]
    domains: frozenset[str]
    read_permission: str
    write_permission: str
    high_risk: frozenset[Operation] = frozenset()


POLICIES = {
    (DataTarget.POSTGRESQL, "CASE_RECORD", "case"): ResourcePolicy(DataTarget.POSTGRESQL, "CASE_RECORD", "case", frozenset({Operation.GET, Operation.LIST, Operation.CREATE, Operation.UPDATE, Operation.UPSERT, Operation.DELETE, Operation.BATCH}), frozenset({"litigation", "default"}), "data:case:read", "data:case:write", frozenset({Operation.DELETE, Operation.BATCH})),
    (DataTarget.MINIO, "OBJECT_DOCUMENT", "document"): ResourcePolicy(DataTarget.MINIO, "OBJECT_DOCUMENT", "document", frozenset({Operation.GET, Operation.LIST, Operation.CREATE, Operation.DELETE}), frozenset({"litigation", "default"}), "data:object:read", "data:object:write", frozenset({Operation.DELETE})),
    (DataTarget.REDIS, "CACHE_ENTRY", "cache"): ResourcePolicy(DataTarget.REDIS, "CACHE_ENTRY", "cache", frozenset({Operation.GET, Operation.UPSERT, Operation.DELETE, Operation.LOCK, Operation.UNLOCK}), frozenset({"litigation", "default"}), "data:cache:read", "data:cache:write"),
    (DataTarget.NEO4J, "GRAPH_ENTITY", "entity"): ResourcePolicy(DataTarget.NEO4J, "GRAPH_ENTITY", "entity", frozenset({Operation.GET, Operation.SEARCH, Operation.CREATE, Operation.UPDATE, Operation.DELETE, Operation.BATCH}), frozenset({"litigation", "default"}), "data:graph:read", "data:graph:write", frozenset({Operation.DELETE, Operation.BATCH})),
    (DataTarget.MILVUS, "VECTOR_EMBEDDING", "embedding"): ResourcePolicy(DataTarget.MILVUS, "VECTOR_EMBEDDING", "embedding", frozenset({Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE}), frozenset({"litigation", "default"}), "data:vector:read", "data:vector:write", frozenset({Operation.DELETE})),
    (DataTarget.TIMESCALEDB, "TIME_SERIES_METRIC", "metric"): ResourcePolicy(DataTarget.TIMESCALEDB, "TIME_SERIES_METRIC", "metric", frozenset({Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH}), frozenset({"litigation", "default"}), "data:timeseries:read", "data:timeseries:write", frozenset({Operation.BATCH})),
}


def redact(value: Any) -> Any:
    sensitive = {"authorization", "cookie", "token", "password", "secret", "connection_string"}
    if isinstance(value, dict):
        return {k: "***REDACTED***" if k.lower() in sensitive else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class InMemoryIdempotency:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str, str], tuple[str, str, DataResponse | None]] = {}

    def digest(self, request: DataRequest) -> str:
        payload = request.model_dump(mode="json", exclude={"trace_id", "metadata"}, exclude_none=True)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def claim(self, request: DataRequest) -> DataResponse | None:
        if request.operation not in WRITE_OPERATIONS:
            return None
        if not request.idempotency_key:
            raise DataControlError("IDEMPOTENCY_KEY_REQUIRED")
        key = (request.auth_context.tenant_id, request.auth_context.biz_domain, request.auth_context.subject_id, request.operation.value, request.idempotency_key)
        digest = self.digest(request)
        record = self.records.get(key)
        if record is None:
            self.records[key] = (digest, "PROCESSING", None)
            return None
        if record[0] != digest:
            raise DataControlError("IDEMPOTENCY_KEY_CONFLICT")
        if record[1] == "PROCESSING":
            raise DataControlError("IDEMPOTENCY_IN_PROGRESS")
        if record[2] is not None:
            replay = record[2].model_copy(deep=True)
            replay.meta["idempotency_replayed"] = True
            return replay
        return None

    def succeed(self, request: DataRequest, response: DataResponse) -> None:
        if request.operation not in WRITE_OPERATIONS or not request.idempotency_key:
            return
        key = (request.auth_context.tenant_id, request.auth_context.biz_domain, request.auth_context.subject_id, request.operation.value, request.idempotency_key)
        self.records[key] = (self.digest(request), "SUCCEEDED", response.model_copy(deep=True))


class ControlledAdapter:
    def __init__(self, target: DataTarget, operations: frozenset[Operation]) -> None:
        self.target = target
        self.name = target.value.lower()
        self.operations = operations
        self.store: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    async def health(self) -> dict[str, str]:
        return {"adapter": self.name, "status": "UP", "mode": "in_memory_phase1"}

    async def execute(self, request: DataRequest, policy: ResourcePolicy) -> dict[str, Any]:
        if request.operation not in self.operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        tenant = request.auth_context.tenant_id
        domain = request.auth_context.biz_domain
        resource_id = request.resource.resource_id or str(request.payload.data.get("id") or "default")
        key = (tenant, domain, f"{policy.resource_type}:{policy.name}", resource_id)
        if request.operation == Operation.GET:
            item = self.store.get(key)
            if item is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return {"data": item, "affected_count": 1}
        if request.operation in {Operation.LIST, Operation.SEARCH}:
            items = [v for k, v in self.store.items() if k[:3] == key[:3]]
            limit = int(request.payload.options.get("limit", 50))
            return {"data": items[:limit], "affected_count": len(items[:limit]), "has_more": len(items) > limit}
        if request.operation in {Operation.CREATE, Operation.UPDATE, Operation.UPSERT, Operation.LOCK, Operation.UNLOCK}:
            self.store[key] = {**request.payload.data, "tenant_id": tenant, "biz_domain": domain, "resource_id": resource_id}
            return {"data": {"resource_id": resource_id}, "affected_count": 1, "resource_version": "v1"}
        if request.operation == Operation.DELETE:
            existed = self.store.pop(key, None) is not None
            return {"data": {"deleted": existed}, "affected_count": int(existed)}
        if request.operation == Operation.BATCH:
            items = request.payload.data.get("items", [])
            return {"data": {"items": [{"status": "OK"} for _ in items]}, "affected_count": len(items)}
        raise DataControlError("OPERATION_NOT_SUPPORTED")


class DataControlService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.idempotency = InMemoryIdempotency()
        self.audit: list[dict[str, Any]] = []
        self.adapters = {
            DataTarget.POSTGRESQL: ControlledAdapter(DataTarget.POSTGRESQL, frozenset({Operation.GET, Operation.LIST, Operation.CREATE, Operation.UPDATE, Operation.UPSERT, Operation.DELETE, Operation.BATCH})),
            DataTarget.MINIO: ControlledAdapter(DataTarget.MINIO, frozenset({Operation.GET, Operation.CREATE, Operation.DELETE, Operation.LIST})),
            DataTarget.REDIS: ControlledAdapter(DataTarget.REDIS, frozenset({Operation.GET, Operation.UPSERT, Operation.DELETE, Operation.LOCK, Operation.UNLOCK})),
            DataTarget.NEO4J: ControlledAdapter(DataTarget.NEO4J, frozenset({Operation.GET, Operation.SEARCH, Operation.CREATE, Operation.UPDATE, Operation.DELETE, Operation.BATCH})),
            DataTarget.MILVUS: ControlledAdapter(DataTarget.MILVUS, frozenset({Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE})),
            DataTarget.TIMESCALEDB: ControlledAdapter(DataTarget.TIMESCALEDB, frozenset({Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH})),
        }

    async def dispatch(self, request: DataRequest) -> DataResponse:
        started = perf_counter()
        trace_id = request.trace_id or f"trace_{uuid4().hex}"
        policy = POLICIES.get((request.resource.target, request.resource.type, request.resource.name))
        if policy is None:
            raise DataControlError("RESOURCE_TYPE_UNKNOWN")
        if request.auth_context.biz_domain not in policy.domains:
            raise DataControlError("AUTH_SCOPE_MISMATCH")
        if request.operation not in policy.operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        permissions = set(request.auth_context.permissions)
        if "DATA_CONTROL_ADMIN" not in request.auth_context.roles:
            required = {policy.read_permission}
            if request.operation in WRITE_OPERATIONS:
                required.add(policy.write_permission)
            if request.operation in policy.high_risk:
                required.add("data:high-risk:execute")
            if not required.issubset(permissions):
                raise DataControlError("PERMISSION_DENIED")
        if request.transaction and request.transaction.mode == "ATOMIC" and request.resource.target not in {DataTarget.POSTGRESQL, DataTarget.NEO4J, DataTarget.TIMESCALEDB}:
            raise DataControlError("TRANSACTION_NOT_SUPPORTED")
        replay = self.idempotency.claim(request)
        if replay is not None:
            self._audit(request, trace_id, "REPLAYED", "OK", None)
            return replay
        adapter = self.adapters.get(policy.target)
        if adapter is None:
            raise DataControlError("ADAPTER_NOT_REGISTERED")
        result = await adapter.execute(request, policy)
        duration_ms = round((perf_counter() - started) * 1000)
        response = DataResponse(
            request_id=request.request_id,
            trace_id=trace_id,
            success=True,
            code="OK",
            message="success",
            data=result.get("data"),
            page={"cursor": None, "limit": int(request.payload.options.get("limit", 50)), "has_more": bool(result.get("has_more", False))} if request.operation in {Operation.LIST, Operation.SEARCH} else None,
            meta={"adapter": adapter.name, "route_id": f"route_{uuid4().hex}", "duration_ms": duration_ms, "affected_count": result.get("affected_count", 0), "resource_version": result.get("resource_version"), "idempotency_replayed": False},
        )
        self.idempotency.succeed(request, response)
        self._audit(request, trace_id, "SUCCEEDED", "OK", adapter.name)
        return response

    def _audit(self, request: DataRequest, trace_id: str, status: str, code: str, adapter: str | None) -> None:
        self.audit.append({"tenant_id": request.auth_context.tenant_id, "biz_domain": request.auth_context.biz_domain, "subject_id": request.auth_context.subject_id, "request_id": request.request_id, "trace_id": trace_id, "operation": request.operation.value, "resource": f"{request.resource.type}:{request.resource.name}", "adapter": adapter, "status": status, "code": code, "payload_digest": hashlib.sha256(repr(redact(request.payload.model_dump())).encode()).hexdigest()})


def error_body(request_id: str, trace_id: str, exc: DataControlError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=DataResponse(request_id=request_id, trace_id=trace_id, success=False, code=exc.code, message=exc.message, error={"category": exc.category, "retryable": exc.retryable, "details": [], "incident_id": exc.incident_id}, meta={}).model_dump(mode="json", exclude_none=True))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    service = DataControlService(settings)
    app = FastAPI(title=settings.app_name, version="0.1.0")

    @app.exception_handler(DataControlError)
    async def handle_domain_error(request: Any, exc: DataControlError) -> JSONResponse:
        return error_body(request.headers.get("x-request-id") or "req_unavailable", request.headers.get("x-trace-id") or f"trace_{uuid4().hex}", exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Any, exc: RequestValidationError) -> JSONResponse:
        code = "IDEMPOTENCY_KEY_REQUIRED" if any("idempotency_key" in item["msg"] for item in exc.errors()) else "REQUEST_SCHEMA_INVALID"
        domain_error = DataControlError(code)
        return error_body(request.headers.get("x-request-id") or "req_unavailable", request.headers.get("x-trace-id") or f"trace_{uuid4().hex}", domain_error)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/ready")
    async def ready() -> dict[str, Any]:
        health = [await adapter.health() for adapter in service.adapters.values()]
        return {"status": "UP", "adapters": health}

    @app.post("/data/dispatch")
    async def dispatch(request: DataRequest) -> JSONResponse:
        response = await service.dispatch(request)
        return JSONResponse(status_code=200, content=response.model_dump(mode="json", exclude_none=True))

    return app
