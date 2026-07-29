import re
from collections.abc import Mapping, Sequence
from typing import Any

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "secret",
    "session_secret",
    "capability_token",
    "password",
}
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"X-Amz-Signature=[^&\s]+", re.IGNORECASE),
    re.compile(r"(api_key|session_secret)\s*[=:]\s*[^,\s]+", re.IGNORECASE),
)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    return value
