from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from file_media_stream_service.application.dto.contracts import RequestContext
from file_media_stream_service.domain.entities.models import (
    AuditEvent,
    FileResource,
    FileResourceVersion,
    FileUploadSession,
    ProcessingJob,
    RangeAccessGrant,
    StreamEvent,
    StreamSession,
    UploadPartGrant,
)


class FileRepository(Protocol):
    async def add(self, resource: FileResource) -> None: ...
    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> FileResource | None: ...
    async def save(self, resource: FileResource) -> None: ...


class FileVersionRepository(Protocol):
    async def add(self, version: FileResourceVersion) -> None: ...
    async def list_by_scope_and_resource(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> list[FileResourceVersion]: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, version_id: str
    ) -> FileResourceVersion | None: ...
    async def save(self, version: FileResourceVersion) -> None: ...


class FileUploadSessionRepository(Protocol):
    async def add(self, upload: FileUploadSession) -> None: ...
    async def save(self, upload: FileUploadSession) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, upload_id: str
    ) -> FileUploadSession | None: ...
    async def list_by_scope_and_resource(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> list[FileUploadSession]: ...


class StreamSessionRepository(Protocol):
    async def add(self, session: StreamSession) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamSession | None: ...
    async def save(self, session: StreamSession) -> None: ...
    async def list_recoverable(self, tenant_id: str, biz_domain: str) -> list[StreamSession]: ...
    async def list_recovery_scopes(self) -> list[tuple[str, str]]: ...


class StreamEventSink(Protocol):
    async def write_stream_event(self, event: StreamEvent) -> None: ...


class ProcessingJobRepository(Protocol):
    async def add(self, job: ProcessingJob) -> None: ...
    async def save(self, job: ProcessingJob) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, job_id: str
    ) -> ProcessingJob | None: ...


class IdempotencyStore(Protocol):
    async def reserve(
        self,
        scope: tuple[str, ...],
        request_hash: str,
    ) -> tuple[str, dict[str, Any] | None]: ...
    async def wait(self, scope: tuple[str, ...]) -> None: ...
    async def complete(
        self, scope: tuple[str, ...], request_hash: str, result: dict[str, Any]
    ) -> None: ...
    async def fail(self, scope: tuple[str, ...]) -> None: ...


class IdentityVerifier(Protocol):
    async def verify(self, context: RequestContext) -> None: ...


class CapabilityTokenVerifier(Protocol):
    async def verify_capability(self, context: RequestContext, operation: str) -> None: ...


class AuthorizationPolicy(Protocol):
    async def authorize(
        self, context: RequestContext, operation: str, resource_scope: str | None
    ) -> None: ...


class QuotaChecker(Protocol):
    async def check(self, context: RequestContext, operation: str) -> None: ...


class ReplayProtector(Protocol):
    async def check_and_record(self, context: RequestContext) -> None: ...


class AuditSink(Protocol):
    async def write(self, event: AuditEvent) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierFactory(Protocol):
    def new_id(self, prefix: str) -> str: ...


@dataclass(frozen=True, slots=True)
class UploadHandle:
    provider_upload_id: str


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    size_bytes: int
    checksum: str
    content_type: str | None


class ObjectStorage(Protocol):
    async def initialize_upload(self, object_key: str, mime_type: str, size_bytes: int) -> str: ...
    async def create_multipart_upload(
        self, object_key: str, mime_type: str = "application/octet-stream"
    ) -> UploadHandle: ...
    async def complete_multipart_upload(
        self, object_key: str, provider_upload_id: str, parts: tuple[tuple[int, str], ...]
    ) -> StoredObjectMetadata: ...
    async def abort_multipart_upload(self, object_key: str, provider_upload_id: str) -> None: ...
    async def abort_upload(self, object_key: str) -> None: ...
    async def get_metadata(self, object_key: str) -> StoredObjectMetadata: ...
    async def create_download_url(self, object_key: str) -> tuple[str, datetime]: ...
    def stream_range(self, object_key: str, offset: int, length: int) -> AsyncIterator[bytes]: ...
    async def delete(self, object_key: str) -> None: ...
    async def upload_part_content(
        self, object_key: str, provider_upload_id: str, part_number: int, content: bytes
    ) -> str: ...
    async def upload_part_stream(
        self,
        object_key: str,
        provider_upload_id: str,
        part_number: int,
        content: AsyncIterator[bytes],
        content_length: int,
    ) -> str: ...


class RangeAccessGrantStore(Protocol):
    async def issue(self, grant: RangeAccessGrant) -> None: ...
    async def consume(self, reference_id: str) -> RangeAccessGrant | None: ...


class UploadPartGrantStore(Protocol):
    async def issue(self, grant: UploadPartGrant) -> None: ...
    async def consume(self, reference_id: str) -> UploadPartGrant | None: ...


class MalwareScannerPort(Protocol):
    async def validate_metadata(
        self, filename: str, mime_type: str, size_bytes: int, checksum: str
    ) -> None: ...


class MediaServer(Protocol):
    async def create_session(
        self, protocol: str, direction: str, lease_expires_at: datetime
    ) -> str: ...
    async def close_session(self, endpoint_reference: str) -> None: ...


class Processor(Protocol):
    async def submit(
        self, processor_type: str, input_resource_id: str, options: Mapping[str, Any]
    ) -> None: ...


class EventBus(Protocol):
    async def publish(self, event_name: str, payload: Mapping[str, Any]) -> None: ...


class ReconciliationStore(Protocol):
    async def record(self, key: str, kind: str, payload: Mapping[str, Any]) -> None: ...
    async def resolve(self, key: str, tenant_id: str, biz_domain: str) -> None: ...
    async def list_pending(self, kind: str) -> list[tuple[str, dict[str, Any]]]: ...


class TransactionManager(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


class ProvisioningCompensator(Protocol):
    def begin(self) -> None: ...
    async def register(self, session: StreamSession, fencing_token: int) -> None: ...
    async def compensate(self) -> None: ...
    def clear(self) -> None: ...


class FileMetadataCommitTracker(Protocol):
    def begin(self) -> None: ...
    def register(
        self,
        tenant_id: str,
        biz_domain: str,
        resource_id: str,
        version_id: str,
    ) -> None: ...
    def register_delete(
        self,
        tenant_id: str,
        biz_domain: str,
        resource_id: str,
        version_id: str | None,
    ) -> None: ...
    async def reconcile(self) -> None: ...
    def clear(self) -> None: ...
