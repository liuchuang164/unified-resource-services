from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from time import perf_counter
from typing import Any
from uuid import uuid4

from minio import Minio

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    mapping_from,
)
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext
from data_control_service.infrastructure.minio.content import MinIOContentValidator
from data_control_service.infrastructure.minio.error_mapper import MinIOErrorMapper
from data_control_service.infrastructure.minio.executor import MinIOExecutor
from data_control_service.infrastructure.minio.key_builder import MinIOObjectKeyBuilder
from data_control_service.infrastructure.minio.records import (
    ObjectRecord,
    ObjectStatus,
    UploadMode,
)
from data_control_service.infrastructure.observability.metrics import metrics_registry
from data_control_service.infrastructure.persistence.repositories.sqlalchemy_object_record import (
    SQLAlchemyObjectRecordRepository,
)

FORBIDDEN_MINIO_KEYS = {
    "bucket",
    "bucket_name",
    "object_key",
    "physical_path",
    "local_path",
    "filesystem_path",
    "endpoint",
    "access_key",
    "secret_key",
    "minio_url",
    "s3_url",
}


@dataclass
class _MemoryObject:
    logical_object_id: str
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None
    status: ObjectStatus
    content: bytes
    created_at: datetime
    updated_at: datetime


class MinIOMapping:
    def __init__(self, command: AdapterCommand, settings: Settings) -> None:
        mapping = mapping_from(command)
        config = {**mapping.physical_mapping}
        self.resource_type = mapping.definition.resource_type
        self.resource_name = mapping.definition.logical_name
        self.bucket_name = str(
            config.get("bucket_name") or config.get("bucket") or settings.minio_default_bucket
        )
        self.object_prefix_template = str(
            config.get("object_prefix_template")
            or (
                "tenant/{tenant_id}/{biz_domain}/{resource_name}/"
                "{yyyy}/{mm}/{logical_object_id}/{safe_filename}"
            )
        )
        self.allowed_content_types = set(
            config.get("allowed_content_types") or settings.minio_allowed_content_types.split(",")
        )
        self.allowed_extensions = set(
            config.get("allowed_extensions") or settings.minio_allowed_extensions.split(",")
        )
        self.max_object_size_bytes = min(
            int(config.get("max_object_size_bytes") or settings.minio_max_object_size_bytes),
            settings.minio_max_object_size_bytes,
        )
        self.allow_overwrite = bool(config.get("allow_overwrite", False))
        self.allow_presigned_upload = bool(config.get("allow_presigned_upload", True))
        self.allow_presigned_download = bool(config.get("allow_presigned_download", True))
        self.default_upload_url_ttl_seconds = min(
            int(
                config.get("default_upload_url_ttl_seconds")
                or settings.minio_default_presigned_upload_ttl_seconds
            ),
            settings.minio_max_presigned_ttl_seconds,
        )
        self.default_download_url_ttl_seconds = min(
            int(
                config.get("default_download_url_ttl_seconds")
                or settings.minio_default_presigned_download_ttl_seconds
            ),
            settings.minio_max_presigned_ttl_seconds,
        )
        self.max_presigned_ttl_seconds = min(
            int(
                config.get("max_presigned_ttl_seconds") or settings.minio_max_presigned_ttl_seconds
            ),
            settings.minio_max_presigned_ttl_seconds,
        )
        self.metadata_allowlist = set(config.get("metadata_allowlist") or ["description", "tags"])


class MinIOPayloadValidator:
    @classmethod
    def reject_forbidden(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in FORBIDDEN_MINIO_KEYS:
                    metrics_registry.increment("minio_path_rejected_total")
                    raise DataControlError("OBJECT_PATH_INVALID")
                cls.reject_forbidden(item)
        elif isinstance(value, list):
            for item in value:
                cls.reject_forbidden(item)
        elif isinstance(value, str):
            lowered = value.lower()
            if lowered.startswith(("file://", "s3://", "minio://")):
                metrics_registry.increment("minio_path_rejected_total")
                raise DataControlError("OBJECT_PATH_INVALID")

    @staticmethod
    def logical_object_id(command: AdapterCommand, data: dict[str, Any]) -> str:
        return str(
            data.get("logical_object_id")
            or data.get("object_id")
            or command.validated_payload.get("resource_id")
            or ""
        )


class InMemoryMinIOAdapter(DataAdapter):
    name = "minio"
    target = DataTarget.MINIO

    def __init__(self, max_size_bytes: int = 10_485_760, max_url_ttl_seconds: int = 900) -> None:
        self._objects: dict[tuple[str, str, str], _MemoryObject] = {}
        self._settings = Settings(
            minio_max_object_size_bytes=max_size_bytes,
            minio_max_presigned_ttl_seconds=max_url_ttl_seconds,
        )
        self._key_builder = MinIOObjectKeyBuilder()

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.EXISTS,
                    Operation.LIST,
                    Operation.CREATE,
                    Operation.DELETE,
                    Operation.PRESIGN_UPLOAD,
                    Operation.UPLOAD_COMPLETE,
                    Operation.PRESIGN_DOWNLOAD,
                }
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
        data = dict(command.validated_payload.get("data", {}))
        options = dict(command.validated_payload.get("options", {}))
        MinIOPayloadValidator.reject_forbidden(data)
        mapping = MinIOMapping(command, self._settings)
        if command.operation == Operation.CREATE:
            return self._create(command, context, mapping, data)
        if command.operation == Operation.PRESIGN_UPLOAD:
            return self._presign_upload(command, context, mapping, data, options)
        logical_object_id = MinIOPayloadValidator.logical_object_id(command, data)
        if command.operation == Operation.UPLOAD_COMPLETE:
            return self._complete(command, mapping, data, logical_object_id)
        if command.operation == Operation.GET:
            return self._get(command, logical_object_id)
        if command.operation == Operation.EXISTS:
            return self._exists(command, logical_object_id)
        if command.operation == Operation.LIST:
            return self._list(command)
        if command.operation == Operation.PRESIGN_DOWNLOAD:
            return self._presign_download(command, mapping, logical_object_id, options)
        if command.operation == Operation.DELETE:
            return self._delete(command, logical_object_id)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    def _create(
        self,
        command: AdapterCommand,
        context: ExecutionContext,
        mapping: MinIOMapping,
        data: dict[str, Any],
    ) -> AdapterResult:
        content = _payload_content(data)
        filename = self._key_builder.safe_filename(str(data.get("filename") or "object.bin"))
        content_type = str(data.get("content_type") or "")
        validator = MinIOContentValidator(
            allowed_content_types=mapping.allowed_content_types,
            allowed_extensions=mapping.allowed_extensions,
            max_object_size_bytes=mapping.max_object_size_bytes,
        )
        validator.validate(
            content=content,
            filename=filename,
            content_type=content_type,
            declared_size=int(data.get("size_bytes") or len(content)),
        )
        logical_object_id = str(data.get("logical_object_id") or f"obj_{uuid4().hex}")
        key = (*command.scope, logical_object_id)
        if key in self._objects and not mapping.allow_overwrite:
            raise DataControlError("OBJECT_CONFLICT")
        now = datetime.now(UTC)
        checksum = hashlib.sha256(content).hexdigest()
        self._objects[key] = _MemoryObject(
            logical_object_id=logical_object_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=checksum,
            status=ObjectStatus.AVAILABLE,
            content=content,
            created_at=now,
            updated_at=now,
        )
        metrics_registry.increment("minio_upload_total")
        metrics_registry.increment("minio_upload_bytes_total", len(content))
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(content),
                "checksum_sha256": checksum,
                "status": ObjectStatus.AVAILABLE.value,
                "upload_mode": UploadMode.PROXY.value,
            },
            affected_count=1,
        )

    def _presign_upload(
        self,
        command: AdapterCommand,
        context: ExecutionContext,
        mapping: MinIOMapping,
        data: dict[str, Any],
        options: dict[str, Any],
    ) -> AdapterResult:
        if not mapping.allow_presigned_upload:
            raise DataControlError("PRESIGNED_URL_NOT_ALLOWED")
        filename = self._key_builder.safe_filename(str(data.get("filename") or "object.bin"))
        content_type = str(data.get("content_type") or "")
        size_bytes = int(data.get("size_bytes") or 0)
        MinIOContentValidator(
            allowed_content_types=mapping.allowed_content_types,
            allowed_extensions=mapping.allowed_extensions,
            max_object_size_bytes=mapping.max_object_size_bytes,
        ).validate_metadata(filename=filename, content_type=content_type, size_bytes=size_bytes)
        logical_object_id = str(data.get("logical_object_id") or f"obj_{uuid4().hex}")
        ttl = _ttl(
            options, "presigned_url_ttl_seconds", mapping.default_upload_url_ttl_seconds, mapping
        )
        self._objects[(*command.scope, logical_object_id)] = _MemoryObject(
            logical_object_id,
            filename,
            content_type,
            size_bytes,
            None,
            ObjectStatus.PENDING_UPLOAD,
            b"",
            datetime.now(UTC),
            datetime.now(UTC),
        )
        metrics_registry.increment("minio_presigned_upload_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "upload_url": f"https://presigned.invalid/upload/{logical_object_id}",
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
                "required_headers": {"Content-Type": content_type},
                "max_size_bytes": mapping.max_object_size_bytes,
                "status": ObjectStatus.PENDING_UPLOAD.value,
            },
            affected_count=1,
        )

    def _complete(
        self,
        command: AdapterCommand,
        mapping: MinIOMapping,
        data: dict[str, Any],
        logical_object_id: str,
    ) -> AdapterResult:
        obj = self._must_get(command, logical_object_id)
        obj.status = ObjectStatus.AVAILABLE
        obj.updated_at = datetime.now(UTC)
        return AdapterResult(status="OK", data=self._public(obj), affected_count=1)

    def _get(self, command: AdapterCommand, logical_object_id: str) -> AdapterResult:
        return AdapterResult(
            status="OK",
            data=self._public(self._must_get(command, logical_object_id)),
            affected_count=1,
        )

    def _exists(self, command: AdapterCommand, logical_object_id: str) -> AdapterResult:
        obj = self._objects.get((*command.scope, logical_object_id))
        exists = obj is not None and obj.status == ObjectStatus.AVAILABLE
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "exists": exists,
                "status": obj.status.value if obj else "MISSING",
            },
            affected_count=int(exists),
        )

    def _list(self, command: AdapterCommand) -> AdapterResult:
        tenant_id, biz_domain = command.scope
        items = [
            self._public(obj)
            for (tenant, biz, _), obj in self._objects.items()
            if tenant == tenant_id and biz == biz_domain and obj.status != ObjectStatus.DELETED
        ]
        return AdapterResult(status="OK", data=items, affected_count=len(items))

    def _presign_download(
        self,
        command: AdapterCommand,
        mapping: MinIOMapping,
        logical_object_id: str,
        options: dict[str, Any],
    ) -> AdapterResult:
        if not mapping.allow_presigned_download:
            raise DataControlError("PRESIGNED_URL_NOT_ALLOWED")
        obj = self._must_get(command, logical_object_id)
        ttl = _ttl(
            options, "presigned_url_ttl_seconds", mapping.default_download_url_ttl_seconds, mapping
        )
        metrics_registry.increment("minio_presigned_download_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": obj.logical_object_id,
                "download_url": f"https://presigned.invalid/download/{logical_object_id}",
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
            },
            affected_count=1,
        )

    def _delete(self, command: AdapterCommand, logical_object_id: str) -> AdapterResult:
        obj = self._must_get(command, logical_object_id, allow_deleted=True)
        obj.status = ObjectStatus.DELETED
        obj.updated_at = datetime.now(UTC)
        metrics_registry.increment("minio_delete_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "deleted": True,
                "status": obj.status.value,
            },
            affected_count=1,
        )

    def _must_get(
        self, command: AdapterCommand, logical_object_id: str, *, allow_deleted: bool = False
    ) -> _MemoryObject:
        if not logical_object_id:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_object_id is required")
        obj = self._objects.get((*command.scope, logical_object_id))
        if obj is None or (obj.status == ObjectStatus.DELETED and not allow_deleted):
            raise DataControlError("RESOURCE_NOT_FOUND")
        return obj

    @staticmethod
    def _public(obj: _MemoryObject) -> dict[str, object]:
        return {
            "logical_object_id": obj.logical_object_id,
            "filename": obj.filename,
            "content_type": obj.content_type,
            "size_bytes": obj.size_bytes,
            "checksum_sha256": obj.checksum_sha256,
            "status": obj.status.value,
            "created_at": obj.created_at.isoformat(),
            "updated_at": obj.updated_at.isoformat(),
        }


class MinIOObjectAdapter(InMemoryMinIOAdapter):
    def __init__(
        self,
        *,
        client: Minio,
        executor: MinIOExecutor,
        object_repository: SQLAlchemyObjectRecordRepository,
        settings: Settings,
    ) -> None:
        super().__init__(
            settings.minio_max_object_size_bytes, settings.minio_max_presigned_ttl_seconds
        )
        self._client = client
        self._executor = executor
        self._object_repository = object_repository
        self._settings = settings

    def capabilities(self) -> AdapterCapabilities:
        base = super().capabilities()
        return AdapterCapabilities(
            operations=base.operations,
            supports_transactions=False,
            supports_atomic_transaction=False,
            supports_cursor_pagination=True,
            timeout_ms=int(self._settings.minio_read_timeout_seconds * 1000),
            required=self._settings.minio_adapter_required,
        )

    async def health(self) -> AdapterHealth:
        try:
            await self._executor.run(
                lambda: self._client.bucket_exists(self._settings.minio_default_bucket)
            )
            return AdapterHealth(
                status="UP",
                details={"adapter": self.name, "mode": "minio"},
                required=self._settings.minio_adapter_required,
            )
        except Exception:
            return AdapterHealth(
                status="DOWN",
                details={"adapter": self.name, "mode": "minio"},
                required=self._settings.minio_adapter_required,
            )

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        started = perf_counter()
        try:
            result = await self._execute_real(command, context)
            metrics_registry.increment("minio_operation_total")
            metrics_registry.observe("minio_operation_latency_seconds", perf_counter() - started)
            return result
        except Exception as exc:
            error = MinIOErrorMapper.to_error(exc)
            metrics_registry.increment("minio_operation_failure_total")
            raise error from exc

    async def _execute_real(
        self, command: AdapterCommand, context: ExecutionContext
    ) -> AdapterResult:
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        data = dict(command.validated_payload.get("data", {}))
        options = dict(command.validated_payload.get("options", {}))
        MinIOPayloadValidator.reject_forbidden(data)
        mapping = MinIOMapping(command, self._settings)
        if command.operation == Operation.CREATE:
            return await self._real_create(command, context, mapping, data)
        if command.operation == Operation.PRESIGN_UPLOAD:
            return await self._real_presign_upload(command, context, mapping, data, options)
        logical_object_id = MinIOPayloadValidator.logical_object_id(command, data)
        if command.operation == Operation.UPLOAD_COMPLETE:
            return await self._real_complete(command, mapping, data, logical_object_id)
        if command.operation == Operation.GET:
            return await self._real_get(command, mapping, logical_object_id)
        if command.operation == Operation.EXISTS:
            return await self._real_exists(command, mapping, logical_object_id)
        if command.operation == Operation.LIST:
            return await self._real_list(command, mapping, options)
        if command.operation == Operation.PRESIGN_DOWNLOAD:
            return await self._real_presign_download(command, mapping, logical_object_id, options)
        if command.operation == Operation.DELETE:
            return await self._real_delete(command, mapping, logical_object_id)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    async def _real_create(
        self,
        command: AdapterCommand,
        context: ExecutionContext,
        mapping: MinIOMapping,
        data: dict[str, Any],
    ) -> AdapterResult:
        content = _payload_content(data)
        filename = self._key_builder.safe_filename(str(data.get("filename") or "object.bin"))
        content_type = str(data.get("content_type") or "")
        validator = self._validator(mapping)
        validator.validate(
            content=content,
            filename=filename,
            content_type=content_type,
            declared_size=int(data.get("size_bytes") or len(content)),
        )
        logical_object_id = str(data.get("logical_object_id") or f"obj_{uuid4().hex}")
        existing = await self._record(command, mapping, logical_object_id)
        if existing and existing.status != ObjectStatus.DELETED and not mapping.allow_overwrite:
            raise DataControlError("OBJECT_CONFLICT")
        object_key = self._key_builder.object_key(
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_name=mapping.resource_name,
            logical_object_id=logical_object_id,
            safe_filename=filename,
            prefix_template=mapping.object_prefix_template,
        )
        checksum = hashlib.sha256(content).hexdigest()
        try:
            response = await self._executor.run(
                lambda: self._client.put_object(
                    mapping.bucket_name,
                    object_key,
                    BytesIO(content),
                    length=len(content),
                    content_type=content_type,
                    metadata={"x-amz-meta-sha256": checksum},
                )
            )
        except Exception:
            await self._executor.run(
                lambda: self._client.remove_object(mapping.bucket_name, object_key)
            )
            metrics_registry.increment("minio_upload_failure_total")
            raise
        record = await self._object_repository.create(
            logical_object_id=logical_object_id,
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_type=mapping.resource_type,
            resource_name=mapping.resource_name,
            bucket_reference=mapping.bucket_name,
            object_key=object_key,
            object_key_digest=self._key_builder.digest(object_key),
            safe_filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=checksum,
            etag=getattr(response, "etag", None),
            status=ObjectStatus.AVAILABLE,
            upload_mode=UploadMode.PROXY,
            created_by=context.subject_id,
            metadata=self._metadata(data, mapping),
        )
        metrics_registry.increment("minio_upload_total")
        metrics_registry.increment("minio_upload_bytes_total", len(content))
        return AdapterResult(status="OK", data=_public_record(record), affected_count=1)

    async def _real_presign_upload(
        self,
        command: AdapterCommand,
        context: ExecutionContext,
        mapping: MinIOMapping,
        data: dict[str, Any],
        options: dict[str, Any],
    ) -> AdapterResult:
        if not mapping.allow_presigned_upload:
            raise DataControlError("PRESIGNED_URL_NOT_ALLOWED")
        filename = self._key_builder.safe_filename(str(data.get("filename") or "object.bin"))
        content_type = str(data.get("content_type") or "")
        size_bytes = int(data.get("size_bytes") or 0)
        self._validator(mapping).validate_metadata(
            filename=filename, content_type=content_type, size_bytes=size_bytes
        )
        logical_object_id = str(data.get("logical_object_id") or f"obj_{uuid4().hex}")
        existing = await self._record(command, mapping, logical_object_id)
        if existing and existing.status != ObjectStatus.DELETED and not mapping.allow_overwrite:
            raise DataControlError("OBJECT_CONFLICT")
        object_key = self._key_builder.object_key(
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_name=mapping.resource_name,
            logical_object_id=logical_object_id,
            safe_filename=filename,
            prefix_template=mapping.object_prefix_template,
        )
        ttl = _ttl(
            options, "presigned_url_ttl_seconds", mapping.default_upload_url_ttl_seconds, mapping
        )
        record = await self._object_repository.create(
            logical_object_id=logical_object_id,
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_type=mapping.resource_type,
            resource_name=mapping.resource_name,
            bucket_reference=mapping.bucket_name,
            object_key=object_key,
            object_key_digest=self._key_builder.digest(object_key),
            safe_filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=None,
            etag=None,
            status=ObjectStatus.PENDING_UPLOAD,
            upload_mode=UploadMode.PRESIGNED,
            created_by=context.subject_id,
            metadata={
                **self._metadata(data, mapping),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
            },
        )
        url = await self._executor.run(
            lambda: self._client.presigned_put_object(
                mapping.bucket_name, object_key, expires=timedelta(seconds=ttl)
            )
        )
        metrics_registry.increment("minio_presigned_upload_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": record.logical_object_id,
                "upload_url": url,
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
                "required_headers": {"Content-Type": content_type},
                "max_size_bytes": mapping.max_object_size_bytes,
                "status": record.status.value,
            },
            affected_count=1,
        )

    async def _real_complete(
        self,
        command: AdapterCommand,
        mapping: MinIOMapping,
        data: dict[str, Any],
        logical_object_id: str,
    ) -> AdapterResult:
        record = await self._must_record(command, mapping, logical_object_id)
        if record.status == ObjectStatus.AVAILABLE:
            return AdapterResult(status="OK", data=_public_record(record), affected_count=1)
        stat = await self._executor.run(
            lambda: self._client.stat_object(mapping.bucket_name, record.object_key)
        )
        content = await self._read_object(mapping.bucket_name, record.object_key)
        self._validator(mapping).validate(
            content=content,
            filename=record.safe_filename,
            content_type=record.content_type,
            declared_size=int(getattr(stat, "size", len(content))),
        )
        checksum = hashlib.sha256(content).hexdigest()
        updated = await self._object_repository.mark_available(
            record,
            size_bytes=len(content),
            checksum_sha256=checksum,
            etag=getattr(stat, "etag", None),
            content_type=record.content_type,
        )
        return AdapterResult(status="OK", data=_public_record(updated), affected_count=1)

    async def _real_get(
        self, command: AdapterCommand, mapping: MinIOMapping, logical_object_id: str
    ) -> AdapterResult:
        record = await self._must_record(command, mapping, logical_object_id)
        if record.status == ObjectStatus.DELETED:
            raise DataControlError("RESOURCE_NOT_FOUND")
        return AdapterResult(status="OK", data=_public_record(record), affected_count=1)

    async def _real_exists(
        self, command: AdapterCommand, mapping: MinIOMapping, logical_object_id: str
    ) -> AdapterResult:
        record = await self._record(command, mapping, logical_object_id)
        exists = record is not None and record.status == ObjectStatus.AVAILABLE
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "exists": exists,
                "status": record.status.value if record else "MISSING",
            },
            affected_count=int(exists),
        )

    async def _real_list(
        self, command: AdapterCommand, mapping: MinIOMapping, options: dict[str, Any]
    ) -> AdapterResult:
        status_value = str(options.get("status") or ObjectStatus.AVAILABLE.value)
        limit = min(int(options.get("limit") or 50), self._settings.max_page_limit)
        records = await self._object_repository.list(
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_type=mapping.resource_type,
            resource_name=mapping.resource_name,
            status=ObjectStatus(status_value),
            limit=limit,
        )
        return AdapterResult(
            status="OK",
            data=[_public_record(record) for record in records],
            affected_count=len(records),
        )

    async def _real_presign_download(
        self,
        command: AdapterCommand,
        mapping: MinIOMapping,
        logical_object_id: str,
        options: dict[str, Any],
    ) -> AdapterResult:
        if not mapping.allow_presigned_download:
            raise DataControlError("PRESIGNED_URL_NOT_ALLOWED")
        record = await self._must_record(command, mapping, logical_object_id)
        if record.status != ObjectStatus.AVAILABLE:
            raise DataControlError("RESOURCE_NOT_FOUND")
        ttl = _ttl(
            options, "presigned_url_ttl_seconds", mapping.default_download_url_ttl_seconds, mapping
        )
        url = await self._executor.run(
            lambda: self._client.presigned_get_object(
                mapping.bucket_name, record.object_key, expires=timedelta(seconds=ttl)
            )
        )
        metrics_registry.increment("minio_presigned_download_total")
        metrics_registry.increment("minio_download_authorization_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": record.logical_object_id,
                "download_url": url,
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
            },
            affected_count=1,
        )

    async def _real_delete(
        self, command: AdapterCommand, mapping: MinIOMapping, logical_object_id: str
    ) -> AdapterResult:
        record = await self._must_record(command, mapping, logical_object_id, allow_deleted=True)
        if record.status == ObjectStatus.DELETED:
            return AdapterResult(
                status="OK",
                data={
                    "logical_object_id": logical_object_id,
                    "deleted": True,
                    "status": record.status.value,
                },
                affected_count=0,
            )
        pending = await self._object_repository.mark_delete_pending(record)
        await self._executor.run(
            lambda: self._client.remove_object(mapping.bucket_name, pending.object_key)
        )
        deleted = await self._object_repository.mark_deleted(pending)
        metrics_registry.increment("minio_delete_total")
        return AdapterResult(
            status="OK",
            data={
                "logical_object_id": logical_object_id,
                "deleted": True,
                "status": deleted.status.value,
            },
            affected_count=1,
        )

    async def _record(
        self, command: AdapterCommand, mapping: MinIOMapping, logical_object_id: str
    ) -> ObjectRecord | None:
        if not logical_object_id:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_object_id is required")
        return await self._object_repository.get(
            tenant_id=command.scope[0],
            biz_domain=command.scope[1],
            resource_type=mapping.resource_type,
            resource_name=mapping.resource_name,
            logical_object_id=logical_object_id,
        )

    async def _must_record(
        self,
        command: AdapterCommand,
        mapping: MinIOMapping,
        logical_object_id: str,
        *,
        allow_deleted: bool = False,
    ) -> ObjectRecord:
        record = await self._record(command, mapping, logical_object_id)
        if record is None or (record.status == ObjectStatus.DELETED and not allow_deleted):
            raise DataControlError("RESOURCE_NOT_FOUND")
        return record

    async def _read_object(self, bucket_name: str, object_key: str) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(bucket_name, object_key)
            try:
                chunks = []
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                response.close()
                response.release_conn()

        return await self._executor.run(read)

    def _validator(self, mapping: MinIOMapping) -> MinIOContentValidator:
        return MinIOContentValidator(
            allowed_content_types=mapping.allowed_content_types,
            allowed_extensions=mapping.allowed_extensions,
            max_object_size_bytes=mapping.max_object_size_bytes,
        )

    def _metadata(self, data: dict[str, Any], mapping: MinIOMapping) -> dict[str, object]:
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        return {
            str(key): value
            for key, value in metadata.items()
            if str(key) in mapping.metadata_allowlist
            and isinstance(value, str | int | float | bool)
        }


def _payload_content(data: dict[str, Any]) -> bytes:
    if "content_base64" in data:
        try:
            return base64.b64decode(str(data["content_base64"]), validate=True)
        except Exception as exc:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "content_base64 is invalid") from exc
    if "content_text" in data:
        return str(data["content_text"]).encode()
    raise DataControlError("REQUEST_SCHEMA_INVALID", "object content is required")


def _ttl(options: dict[str, Any], field: str, default_ttl: int, mapping: MinIOMapping) -> int:
    ttl = int(options.get(field) or default_ttl)
    if ttl <= 0 or ttl > mapping.max_presigned_ttl_seconds:
        raise DataControlError("REQUEST_SCHEMA_INVALID", "presigned URL ttl is invalid")
    return ttl


def _public_record(record: ObjectRecord) -> dict[str, object]:
    return {
        "logical_object_id": record.logical_object_id,
        "filename": record.safe_filename,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "checksum_sha256": record.checksum_sha256,
        "status": record.status.value,
        "upload_mode": record.upload_mode.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }
