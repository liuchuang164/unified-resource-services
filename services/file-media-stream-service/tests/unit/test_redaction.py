import json

from file_media_stream_service.observability import redact


def test_sensitive_logs_are_recursively_redacted() -> None:
    output = json.dumps(
        redact(
            {
                "authorization": "Bearer secret-token",
                "nested": {
                    "url": "https://storage/x?X-Amz-Signature=secret",
                    "api_key": "plain",
                    "message": "session_secret=hidden",
                },
            }
        )
    )
    for secret in ("Bearer secret-token", "X-Amz-Signature", "plain", "hidden"):
        assert secret not in output
    assert output.count("[REDACTED]") == 4
