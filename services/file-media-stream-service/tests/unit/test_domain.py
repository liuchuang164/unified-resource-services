from datetime import UTC, datetime, timedelta

import pytest

from file_media_stream_service.domain.entities import FileResource, ProcessingJob, StreamSession
from file_media_stream_service.domain.enums import (
    FileResourceStatus,
    ProcessingJobStatus,
    StreamSessionStatus,
)
from file_media_stream_service.domain.exceptions import InvalidStateTransition

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_file_resource_creation_and_transition() -> None:
    resource = FileResource(
        "res-1",
        "tenant-a",
        "legal",
        "case",
        "case-1",
        "a.pdf",
        "a.pdf",
        "tenant/tenant-a/domain/legal/resource/res-1/1/a.pdf",
        "application/pdf",
        10,
        None,
        FileResourceStatus.PENDING_UPLOAD,
        1,
        "caller",
        NOW,
        NOW,
    )
    resource.transition_to(FileResourceStatus.UPLOADING)
    resource.transition_to(FileResourceStatus.AVAILABLE)
    assert resource.status is FileResourceStatus.AVAILABLE
    assert resource.tenant_id == "tenant-a"


def test_illegal_file_transition_is_rejected() -> None:
    resource = FileResource(
        "res-1",
        "tenant-a",
        "legal",
        "case",
        "case-1",
        "a.pdf",
        "a.pdf",
        "key",
        "application/pdf",
        10,
        None,
        FileResourceStatus.PENDING_UPLOAD,
        1,
        "caller",
        NOW,
        NOW,
    )
    with pytest.raises(InvalidStateTransition):
        resource.transition_to(FileResourceStatus.DELETED)


def test_stream_close_is_idempotent() -> None:
    session = StreamSession(
        "ses-1",
        "tenant-a",
        "legal",
        "caller",
        "WEBRTC",
        "INGRESS",
        StreamSessionStatus.READY,
        NOW + timedelta(minutes=5),
        "ref",
        NOW,
        NOW,
    )
    session.close()
    session.close()
    assert session.status is StreamSessionStatus.CLOSED


def test_stream_active_close_drains_then_closes() -> None:
    session = StreamSession(
        "ses-1",
        "tenant-a",
        "legal",
        "caller",
        "WEBRTC",
        "INGRESS",
        StreamSessionStatus.ACTIVE,
        NOW + timedelta(minutes=5),
        "ref",
        NOW,
        NOW,
    )
    session.close()
    assert session.status is StreamSessionStatus.CLOSED


def test_processing_job_state_machine() -> None:
    job = ProcessingJob(
        "job-1",
        "tenant-a",
        "legal",
        "OCR",
        "res-1",
        (),
        ProcessingJobStatus.PENDING,
        "fake",
        0,
        NOW,
        NOW,
    )
    job.transition_to(ProcessingJobStatus.QUEUED)
    job.transition_to(ProcessingJobStatus.RUNNING)
    job.transition_to(ProcessingJobStatus.SUCCEEDED)
    with pytest.raises(InvalidStateTransition):
        job.transition_to(ProcessingJobStatus.RUNNING)
