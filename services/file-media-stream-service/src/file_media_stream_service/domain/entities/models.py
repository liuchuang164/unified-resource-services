from dataclasses import dataclass, field
from datetime import UTC, datetime

from file_media_stream_service.domain.enums.status import (
    FileResourceStatus,
    GrantStatus,
    ProcessingJobStatus,
    StreamSessionStatus,
)
from file_media_stream_service.domain.exceptions.errors import InvalidStateTransition


def utc_now() -> datetime:
    return datetime.now(UTC)


FILE_TRANSITIONS: dict[FileResourceStatus, frozenset[FileResourceStatus]] = {
    FileResourceStatus.PENDING_UPLOAD: frozenset(
        {FileResourceStatus.UPLOADING, FileResourceStatus.FAILED}
    ),
    FileResourceStatus.UPLOADING: frozenset(
        {FileResourceStatus.AVAILABLE, FileResourceStatus.FAILED}
    ),
    FileResourceStatus.AVAILABLE: frozenset(
        {
            FileResourceStatus.PROCESSING,
            FileResourceStatus.QUARANTINED,
            FileResourceStatus.DELETING,
        }
    ),
    FileResourceStatus.PROCESSING: frozenset(
        {
            FileResourceStatus.AVAILABLE,
            FileResourceStatus.QUARANTINED,
            FileResourceStatus.FAILED,
        }
    ),
    FileResourceStatus.QUARANTINED: frozenset(
        {FileResourceStatus.AVAILABLE, FileResourceStatus.DELETING}
    ),
    FileResourceStatus.DELETING: frozenset({FileResourceStatus.DELETED, FileResourceStatus.FAILED}),
    FileResourceStatus.DELETED: frozenset(),
    FileResourceStatus.FAILED: frozenset({FileResourceStatus.DELETING}),
}

STREAM_TRANSITIONS: dict[StreamSessionStatus, frozenset[StreamSessionStatus]] = {
    StreamSessionStatus.CREATING: frozenset(
        {StreamSessionStatus.READY, StreamSessionStatus.FAILED, StreamSessionStatus.EXPIRED}
    ),
    StreamSessionStatus.READY: frozenset(
        {
            StreamSessionStatus.ACTIVE,
            StreamSessionStatus.DRAINING,
            StreamSessionStatus.CLOSED,
            StreamSessionStatus.FAILED,
            StreamSessionStatus.EXPIRED,
        }
    ),
    StreamSessionStatus.ACTIVE: frozenset(
        {
            StreamSessionStatus.DRAINING,
            StreamSessionStatus.FAILED,
            StreamSessionStatus.EXPIRED,
        }
    ),
    StreamSessionStatus.DRAINING: frozenset(
        {StreamSessionStatus.CLOSED, StreamSessionStatus.FAILED, StreamSessionStatus.EXPIRED}
    ),
    StreamSessionStatus.CLOSED: frozenset(),
    StreamSessionStatus.FAILED: frozenset({StreamSessionStatus.CLOSED}),
    StreamSessionStatus.EXPIRED: frozenset({StreamSessionStatus.CLOSED}),
}

JOB_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.PENDING: frozenset(
        {ProcessingJobStatus.QUEUED, ProcessingJobStatus.CANCELLED}
    ),
    ProcessingJobStatus.QUEUED: frozenset(
        {ProcessingJobStatus.RUNNING, ProcessingJobStatus.FAILED, ProcessingJobStatus.CANCELLED}
    ),
    ProcessingJobStatus.RUNNING: frozenset(
        {
            ProcessingJobStatus.SUCCEEDED,
            ProcessingJobStatus.FAILED,
            ProcessingJobStatus.CANCELLED,
        }
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset({ProcessingJobStatus.QUEUED}),
    ProcessingJobStatus.CANCELLED: frozenset(),
}


def _transition[T](current: T, target: T, transitions: dict[T, frozenset[T]]) -> T:
    if target not in transitions[current]:
        raise InvalidStateTransition(
            f"Cannot transition from {current} to {target}",
            {"from": str(current), "to": str(target)},
        )
    return target


@dataclass(slots=True)
class FileResource:
    resource_id: str
    tenant_id: str
    biz_domain: str
    owner_type: str
    owner_id: str
    original_filename: str
    normalized_filename: str
    object_key: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    status: FileResourceStatus
    version: int
    created_by: str
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def transition_to(self, target: FileResourceStatus) -> None:
        self.status = _transition(self.status, target, FILE_TRANSITIONS)
        self.updated_at = utc_now()


@dataclass(slots=True)
class MediaResource:
    resource_id: str
    media_type: str
    codec: str | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    derived_resource_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class StreamSession:
    session_id: str
    tenant_id: str
    biz_domain: str
    caller_id: str
    protocol: str
    direction: str
    status: StreamSessionStatus
    lease_expires_at: datetime
    endpoint_reference: str
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def transition_to(self, target: StreamSessionStatus) -> None:
        self.status = _transition(self.status, target, STREAM_TRANSITIONS)
        self.updated_at = utc_now()

    def close(self) -> None:
        if self.status is StreamSessionStatus.CLOSED:
            return
        if self.status in {
            StreamSessionStatus.READY,
            StreamSessionStatus.FAILED,
            StreamSessionStatus.EXPIRED,
        }:
            self.transition_to(StreamSessionStatus.CLOSED)
            return
        if self.status is StreamSessionStatus.ACTIVE:
            self.transition_to(StreamSessionStatus.DRAINING)
        if self.status is StreamSessionStatus.DRAINING:
            self.transition_to(StreamSessionStatus.CLOSED)
            return
        raise InvalidStateTransition(f"Cannot close session from {self.status}")


@dataclass(slots=True)
class ProcessingJob:
    job_id: str
    tenant_id: str
    biz_domain: str
    operation: str
    input_resource_id: str
    output_resource_ids: tuple[str, ...]
    status: ProcessingJobStatus
    processor_type: str
    attempt: int
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def transition_to(self, target: ProcessingJobStatus) -> None:
        self.status = _transition(self.status, target, JOB_TRANSITIONS)
        self.updated_at = utc_now()


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    grant_id: str
    tenant_id: str
    biz_domain: str
    subject_type: str
    subject_id: str
    resource_id: str
    allowed_actions: frozenset[str]
    expires_at: datetime
    status: GrantStatus


@dataclass(frozen=True, slots=True)
class AuditEvent:
    audit_id: str
    request_id: str
    trace_id: str
    tenant_id: str
    biz_domain: str
    caller_type: str
    caller_id: str
    operation: str
    resource_id: str | None
    session_id: str | None
    job_id: str | None
    decision: str
    result: str
    error_code: str | None
    duration_ms: int
    created_at: datetime
