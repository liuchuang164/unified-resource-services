import json
from dataclasses import dataclass
from typing import Any

from data_control_service.domain.exceptions import DataControlError


@dataclass(frozen=True)
class RedisSerializedValue:
    payload: str
    value_type: str
    size_bytes: int


class RedisValueSerializer:
    def __init__(self, *, max_value_bytes: int) -> None:
        self._max_value_bytes = max_value_bytes

    def serialize(
        self, value: Any, *, value_type: str, max_value_bytes: int | None = None
    ) -> RedisSerializedValue:
        normalized_type = value_type.upper()
        if normalized_type == "STRING":
            if not isinstance(value, str):
                raise DataControlError("REQUEST_SCHEMA_INVALID", "STRING value must be a string")
            payload = value
        elif normalized_type == "JSON":
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        elif normalized_type == "INTEGER":
            if not isinstance(value, int) or isinstance(value, bool):
                raise DataControlError("REQUEST_SCHEMA_INVALID", "INTEGER value must be an integer")
            payload = str(value)
        else:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "Redis value_type is unsupported")
        size = len(payload.encode("utf-8"))
        limit = min(max_value_bytes or self._max_value_bytes, self._max_value_bytes)
        if size > limit:
            raise DataControlError("PAYLOAD_TOO_LARGE")
        return RedisSerializedValue(payload=payload, value_type=normalized_type, size_bytes=size)

    def deserialize(self, payload: str, *, value_type: str) -> Any:
        normalized_type = value_type.upper()
        if normalized_type == "STRING":
            return payload
        if normalized_type == "JSON":
            return json.loads(payload)
        if normalized_type == "INTEGER":
            return int(payload)
        raise DataControlError("REQUEST_SCHEMA_INVALID", "Redis value_type is unsupported")
