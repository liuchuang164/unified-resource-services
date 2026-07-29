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


class CreateStreamPayload(StrictPayload):
    protocol: Literal["WEBSOCKET", "WEBRTC", "RTMP", "HLS"]
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
    "media.create_stream_session": CreateStreamPayload,
    "media.get_stream_session": SessionIdPayload,
    "media.close_stream_session": SessionIdPayload,
    "media.submit_processing_job": SubmitJobPayload,
    "media.get_processing_job": JobIdPayload,
}

IDEMPOTENT_OPERATIONS = frozenset(
    {
        "file.initialize_upload",
        "media.create_stream_session",
        "media.close_stream_session",
        "media.submit_processing_job",
    }
)
