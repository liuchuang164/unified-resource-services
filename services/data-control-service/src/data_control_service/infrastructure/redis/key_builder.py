from urllib.parse import quote

from data_control_service.domain.exceptions import DataControlError


class RedisKeyBuilder:
    def __init__(self, *, global_prefix: str, max_logical_key_length: int = 256) -> None:
        self._global_prefix = self._clean_segment(global_prefix, "global_prefix")
        self._max_logical_key_length = max_logical_key_length

    def cache_key(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_name: str,
        logical_key: str,
        key_prefix: str | None = None,
    ) -> str:
        return self._join(tenant_id, biz_domain, resource_name, logical_key, key_prefix)

    def lock_key(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_name: str,
        logical_key: str,
        key_prefix: str | None = None,
    ) -> str:
        return self._join(tenant_id, biz_domain, resource_name, logical_key, key_prefix, lock=True)

    def _join(
        self,
        tenant_id: str,
        biz_domain: str,
        resource_name: str,
        logical_key: str,
        key_prefix: str | None,
        *,
        lock: bool = False,
    ) -> str:
        prefix = self._clean_segment(key_prefix or self._global_prefix, "key_prefix")
        logical = self._clean_logical_key(logical_key)
        parts = [
            prefix,
            self._clean_segment(tenant_id, "tenant_id"),
            self._clean_segment(biz_domain, "biz_domain"),
            self._clean_segment(resource_name, "resource_name"),
        ]
        if lock:
            parts.append("lock")
        parts.append(logical)
        return ":".join(parts)

    def _clean_logical_key(self, value: str) -> str:
        if not value or len(value) > self._max_logical_key_length:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_key is invalid")
        if any(ord(ch) < 32 or ch == "\x7f" for ch in value):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_key contains control chars")
        if "\n" in value or "\r" in value:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "logical_key contains newline")
        if "://" in value or value.startswith(self._global_prefix + ":"):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "physical Redis key is forbidden")
        return quote(value, safe="._-")

    @staticmethod
    def _clean_segment(value: str, field: str) -> str:
        if not value or any(ord(ch) < 32 or ch in {":", "\n", "\r"} for ch in value):
            raise DataControlError("CONFIGURATION_INVALID", f"{field} is invalid")
        return quote(value, safe="._-")
