from __future__ import annotations

from minio.error import InvalidResponseError, S3Error, ServerError
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, ReadTimeoutError

from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.observability.metrics import metrics_registry


class MinIOErrorMapper:
    @staticmethod
    def to_error(exc: Exception) -> DataControlError:
        if isinstance(exc, DataControlError):
            return exc
        if isinstance(exc, TimeoutError | ReadTimeoutError | ConnectTimeoutError):
            metrics_registry.increment("minio_timeout_total")
            return DataControlError("ADAPTER_TIMEOUT")
        if isinstance(exc, MaxRetryError | ConnectionError):
            metrics_registry.increment("minio_connection_failure_total")
            return DataControlError("ADAPTER_UNAVAILABLE")
        if isinstance(exc, S3Error):
            code = exc.code
            if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                return DataControlError("ADAPTER_AUTHENTICATION_FAILED")
            if code in {"NoSuchBucket", "BucketNotFound", "NoSuchKey"}:
                return DataControlError("RESOURCE_NOT_FOUND")
            if code in {"EntityTooLarge"}:
                return DataControlError("OBJECT_TOO_LARGE")
            if code in {"InvalidObjectName"}:
                return DataControlError("OBJECT_PATH_INVALID")
            if code in {"PreconditionFailed", "Conflict"}:
                return DataControlError("OBJECT_CONFLICT")
            return DataControlError("ADAPTER_RESPONSE_INVALID")
        if isinstance(exc, InvalidResponseError | ServerError):
            return DataControlError("ADAPTER_RESPONSE_INVALID")
        return DataControlError("ADAPTER_UNAVAILABLE")
