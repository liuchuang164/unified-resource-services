from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = {
    "access_key",
    "api_key",
    "api_secret",
    "authorization",
    "cookie",
    "secret",
    "secret_key",
    "signature",
    "token",
}


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "***REDACTED***" if _sensitive(str(key)) else redact(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def _sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEYS)
