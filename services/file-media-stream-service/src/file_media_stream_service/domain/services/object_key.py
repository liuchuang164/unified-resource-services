import re
import unicodedata

from file_media_stream_service.domain.exceptions.errors import InvalidObjectName

_SCOPE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def validate_scope_segment(value: str, field_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if normalized != value or not _SCOPE.fullmatch(normalized):
        raise InvalidObjectName(f"Invalid {field_name}")
    return normalized


def normalize_filename(filename: str, max_length: int = 180) -> str:
    normalized = unicodedata.normalize("NFKC", filename).strip()
    if (
        not normalized
        or normalized != filename
        or _CONTROL.search(normalized)
        or "/" in normalized
        or "\\" in normalized
        or normalized in {".", ".."}
        or normalized.startswith(("/", "\\"))
        or ".." in normalized
    ):
        raise InvalidObjectName("Invalid original filename")
    safe = _UNSAFE.sub("_", normalized).strip("._")
    if not safe:
        raise InvalidObjectName("Filename has no safe characters")
    if safe.count(".") > 1:
        raise InvalidObjectName("Multiple filename extensions are not allowed")
    if len(safe) > max_length:
        stem, dot, suffix = safe.rpartition(".")
        safe = f"{stem[: max_length - len(suffix) - 1]}.{suffix}" if dot else safe[:max_length]
    return safe


def generate_object_key(
    tenant_id: str,
    biz_domain: str,
    resource_id: str,
    version: int,
    safe_name: str,
) -> str:
    tenant = validate_scope_segment(tenant_id, "tenant_id")
    domain = validate_scope_segment(biz_domain, "biz_domain")
    resource = validate_scope_segment(resource_id, "resource_id")
    if version < 1 or normalize_filename(safe_name) != safe_name:
        raise InvalidObjectName("Invalid object key component")
    return f"tenant/{tenant}/domain/{domain}/resource/{resource}/{version}/{safe_name}"
