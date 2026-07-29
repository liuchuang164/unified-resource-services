from redis.exceptions import (
    AuthenticationError,
    BusyLoadingError,
    ClusterDownError,
    ConnectionError,
    MaxConnectionsError,
    ReadOnlyError,
    RedisError,
    ResponseError,
    TimeoutError,
)

from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.observability.metrics import metrics_registry


class RedisErrorMapper:
    @staticmethod
    def to_error(exc: Exception) -> DataControlError:
        if isinstance(exc, DataControlError):
            return exc
        if isinstance(exc, TimeoutError):
            metrics_registry.increment("redis_timeout_total")
            return DataControlError("ADAPTER_TIMEOUT")
        if isinstance(exc, MaxConnectionsError):
            metrics_registry.increment("redis_pool_exhaustion_total")
            return DataControlError("ADAPTER_CAPACITY_EXCEEDED")
        if isinstance(exc, AuthenticationError):
            return DataControlError("ADAPTER_AUTHENTICATION_FAILED")
        if isinstance(exc, (BusyLoadingError, ReadOnlyError, ClusterDownError, ConnectionError)):
            metrics_registry.increment("redis_connection_failure_total")
            return DataControlError("ADAPTER_UNAVAILABLE")
        if isinstance(exc, ResponseError):
            return DataControlError("ADAPTER_RESPONSE_INVALID")
        if isinstance(exc, RedisError):
            return DataControlError("ADAPTER_UNAVAILABLE")
        return DataControlError("INTERNAL_ERROR")
