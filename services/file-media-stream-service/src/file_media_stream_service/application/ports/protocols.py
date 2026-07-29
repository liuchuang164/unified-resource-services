from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from file_media_stream_service.application.dto.contracts import RequestContext
from file_media_stream_service.domain.entities.models import (
    AuditEvent,
    FileResource,
    ProcessingJob,
    StreamSession,
)


class FileRepository(Protocol):
    async def add(self, resource: FileResource) -> None: ...
    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> FileResource | None: ...


class StreamSessionRepository(Protocol):
    async def add(self, session: StreamSession) -> None: ...
    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamSession | None: ...
    async def save(self, session: StreamSession) -> None: ...


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


class ObjectStorage(Protocol):
    async def initialize_upload(self, object_key: str, mime_type: str, size_bytes: int) -> str: ...
    async def abort_upload(self, object_key: str) -> None: ...


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
    async def resolve(self, key: str) -> None: ...
