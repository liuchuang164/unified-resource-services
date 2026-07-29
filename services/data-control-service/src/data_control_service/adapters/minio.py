from dataclasses import dataclass
from uuid import uuid4

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    mapping_from,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass
class _Object:
    bucket: str
    object_id: str
    object_key: str
    content_type: str
    size_bytes: int
    data: object
    deleted: bool = False


class InMemoryMinIOAdapter(DataAdapter):
    name = "minio"
    target = DataTarget.MINIO

    def __init__(self, max_size_bytes: int = 10_485_760, max_url_ttl_seconds: int = 900) -> None:
        self._objects: dict[tuple[str, str, str], _Object] = {}
        self._max_size_bytes = max_size_bytes
        self._max_url_ttl_seconds = max_url_ttl_seconds

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {Operation.GET, Operation.CREATE, Operation.DELETE, Operation.LIST}
            ),
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=True,
            timeout_ms=5000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        mapping = mapping_from(command)
        bucket = str(mapping.physical_mapping["bucket"])
        tenant_id, biz_domain = command.scope
        data = command.validated_payload.get("data", {})
        if any(
            key in data
            for key in {
                "bucket",
                "object_key",
                "physical_path",
                "endpoint",
                "access_key",
                "secret_key",
            }
        ):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "client storage fields are forbidden")
        resource = mapping.definition.logical_name
        if command.operation == Operation.CREATE:
            filename = str(data.get("filename", ""))
            content_type = str(data.get("content_type", ""))
            size_bytes = int(data.get("size_bytes", 0))
            ttl = int(
                command.validated_payload.get("options", {}).get("presigned_url_ttl_seconds", 0)
                or 0
            )
            if not filename or ".." in filename or filename.startswith("/") or "/../" in filename:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "invalid object filename")
            allowed = (
                mapping.definition.data_constraints.get("allowed_content_types", [])
                if mapping.definition.data_constraints
                else []
            )
            if content_type not in allowed:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "content type is not allowed")
            if size_bytes > self._max_size_bytes:
                raise DataControlError("PAYLOAD_TOO_LARGE")
            if ttl > self._max_url_ttl_seconds:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "presigned URL ttl is too large")
            object_id = f"obj_{uuid4().hex}"
            object_key = f"tenant/{tenant_id}/{biz_domain}/{resource}/{object_id}"
            self._objects[(tenant_id, biz_domain, object_id)] = _Object(
                bucket, object_id, object_key, content_type, size_bytes, data.get("content")
            )
            return AdapterResult(
                status="OK",
                data={"object_id": object_id, "object_key": object_key},
                affected_count=1,
            )
        object_id = str(command.validated_payload.get("resource_id") or data.get("object_id") or "")
        if command.operation == Operation.GET:
            obj = self._objects.get((tenant_id, biz_domain, object_id))
            if obj is None or obj.deleted:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(
                status="OK",
                data={
                    "object_id": obj.object_id,
                    "content_type": obj.content_type,
                    "size_bytes": obj.size_bytes,
                },
                affected_count=1,
            )
        if command.operation == Operation.LIST:
            objects = [
                obj
                for key, obj in self._objects.items()
                if key[:2] == (tenant_id, biz_domain) and not obj.deleted
            ]
            return AdapterResult(
                status="OK",
                data=[
                    {"object_id": obj.object_id, "object_key": obj.object_key} for obj in objects
                ],
                affected_count=len(objects),
            )
        if command.operation == Operation.DELETE:
            obj = self._objects.get((tenant_id, biz_domain, object_id))
            if obj is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            obj.deleted = True
            return AdapterResult(status="OK", data={"deleted": True}, affected_count=1)
        raise DataControlError("OPERATION_NOT_SUPPORTED")
