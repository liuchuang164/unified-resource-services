import pytest
from pydantic import ValidationError

from file_media_stream_service.application.dto import RequestContext, UnifiedResponse
from file_media_stream_service.application.use_cases import canonical_request_hash
from file_media_stream_service.gateway import TOOL_OPERATIONS, TOOL_SCHEMAS


def test_request_context_requires_scope() -> None:
    with pytest.raises(ValidationError):
        RequestContext.model_validate(
            {
                "request_id": "r",
                "trace_id": "t",
                "tenant_id": "",
                "biz_domain": "legal",
                "caller_type": "service",
                "caller_id": "svc",
            }
        )


def test_agent_context_requires_agent_fields() -> None:
    with pytest.raises(ValidationError):
        RequestContext.model_validate(
            {
                "request_id": "r",
                "trace_id": "t",
                "tenant_id": "tenant",
                "biz_domain": "legal",
                "caller_type": "agent",
                "caller_id": "agent",
            }
        )


def test_response_shape_is_enforced() -> None:
    with pytest.raises(ValidationError):
        UnifiedResponse(request_id="r", trace_id="t", success=True, data=None, error=None)


def test_hash_is_canonical_and_payload_sensitive() -> None:
    assert canonical_request_hash({"a": 1, "b": 2}) == canonical_request_hash({"b": 2, "a": 1})
    assert canonical_request_hash({"a": 1}) != canonical_request_hash({"a": 2})


def test_tool_mapping_and_schema_are_frozen() -> None:
    assert TOOL_OPERATIONS["file.initialize_upload"] == "file.initialize_upload"
    assert TOOL_OPERATIONS["media.submit_processing_job"] == "media.submit_processing_job"
    assert TOOL_SCHEMAS["file.initialize_upload"]["additionalProperties"] is False
    assert len(TOOL_OPERATIONS) == 20
    assert TOOL_OPERATIONS["file.read_range"] == "file.read_range"
    assert TOOL_OPERATIONS["file.create_upload_part_urls"] == "file.create_upload_part_urls"
    assert TOOL_OPERATIONS["file.create_version_upload"] == "file.create_version_upload"
