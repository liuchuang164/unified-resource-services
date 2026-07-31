from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitializeUploadPayload(StrictPayload):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0, le=10 * 1024 * 1024 * 1024)
    owner_type: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=128)


class ResourceIdPayload(StrictPayload):
    resource_id: str = Field(min_length=1, max_length=128)


class UploadPartPayload(StrictPayload):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=256)


class UploadIdPayload(ResourceIdPayload):
    upload_id: str = Field(min_length=1, max_length=128)


class CompleteUploadPayload(UploadIdPayload):
    parts: list[UploadPartPayload] = Field(min_length=1, max_length=10_000)
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ReadRangePayload(ResourceIdPayload):
    offset: int = Field(ge=0)
    length: int = Field(ge=1, le=8 * 1024 * 1024)


class CreateStreamPayload(StrictPayload):
    protocol: Literal["WEBSOCKET", "WEBRTC", "RTMP", "HLS", "WS_AUDIO", "WS_VIDEO"]
    direction: Literal["INGRESS", "EGRESS", "BIDIRECTIONAL"]


class SessionIdPayload(StrictPayload):
    session_id: str = Field(min_length=1, max_length=128)


class SubmitJobPayload(StrictPayload):
    operation: Literal["OCR", "ASR", "TRANSCODE", "SLICE", "ANALYZE"]
    input_resource_id: str = Field(min_length=1, max_length=128)
    processor_type: str = Field(min_length=1, max_length=64)
    options: dict[str, Any] = Field(default_factory=dict)


class JobIdPayload(StrictPayload):
    job_id: str = Field(min_length=1, max_length=128)


PAYLOAD_MODELS: dict[str, type[StrictPayload]] = {
    "file.initialize_upload": InitializeUploadPayload,
    "file.get_resource": ResourceIdPayload,
    "file.complete_upload": CompleteUploadPayload,
    "file.abort_upload": UploadIdPayload,
    "file.create_download_url": ResourceIdPayload,
    "file.read_range": ReadRangePayload,
    "file.get_metadata": ResourceIdPayload,
    "file.delete_file": ResourceIdPayload,
    "media.create_stream_session": CreateStreamPayload,
    "media.get_stream_session": SessionIdPayload,
    "media.close_stream_session": SessionIdPayload,
    "media.submit_processing_job": SubmitJobPayload,
    "media.get_processing_job": JobIdPayload,
}

IDEMPOTENT_OPERATIONS = frozenset(
    {
        "file.initialize_upload",
        "file.complete_upload",
        "file.abort_upload",
        "file.delete_file",
        "media.create_stream_session",
        "media.close_stream_session",
        "media.submit_processing_job",
    }
)
