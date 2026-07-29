from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.observability.metrics import metrics_registry


class PostgreSQLErrorMapper:
    @staticmethod
    def to_error(exc: Exception) -> DataControlError:
        if isinstance(exc, DataControlError):
            return exc
        if isinstance(exc, SQLAlchemyTimeoutError):
            metrics_registry.increment("postgresql_pool_timeout_total")
            return DataControlError("ADAPTER_TIMEOUT")
        if isinstance(exc, OperationalError):
            metrics_registry.increment("postgresql_connection_failure_total")
            return DataControlError("ADAPTER_UNAVAILABLE")
        if isinstance(exc, IntegrityError):
            sqlstate = PostgreSQLErrorMapper._sqlstate(exc)
            if sqlstate == "23505":
                return DataControlError("DATA_CONSTRAINT_VIOLATION")
            if sqlstate in {"23503", "23514", "23502"}:
                return DataControlError("DATA_CONSTRAINT_VIOLATION")
            if sqlstate in {"40001", "40P01"}:
                if sqlstate == "40001":
                    metrics_registry.increment("postgresql_serialization_failure_total")
                    metrics_registry.increment("transaction_serialization_failure_total")
                    error_code = "TRANSACTION_SERIALIZATION_FAILURE"
                else:
                    metrics_registry.increment("postgresql_deadlock_total")
                    metrics_registry.increment("transaction_deadlock_total")
                    error_code = "TRANSACTION_DEADLOCK"
                metrics_registry.increment("postgresql_transaction_rollback_total")
                return DataControlError(error_code)
            return DataControlError("DATA_CONSTRAINT_VIOLATION")
        sqlstate = PostgreSQLErrorMapper._sqlstate(exc)
        if sqlstate in {"57014"}:
            metrics_registry.increment("postgresql_statement_timeout_total")
            return DataControlError("ADAPTER_TIMEOUT")
        if sqlstate in {"08000", "08003", "08006", "53300"}:
            metrics_registry.increment("postgresql_connection_failure_total")
            return DataControlError("ADAPTER_UNAVAILABLE")
        if sqlstate in {"40001", "40P01"}:
            if sqlstate == "40001":
                metrics_registry.increment("postgresql_serialization_failure_total")
                metrics_registry.increment("transaction_serialization_failure_total")
                error_code = "TRANSACTION_SERIALIZATION_FAILURE"
            else:
                metrics_registry.increment("postgresql_deadlock_total")
                metrics_registry.increment("transaction_deadlock_total")
                error_code = "TRANSACTION_DEADLOCK"
            metrics_registry.increment("postgresql_transaction_rollback_total")
            return DataControlError(error_code)
        return DataControlError("INTERNAL_ERROR")

    @staticmethod
    def _sqlstate(exc: Exception) -> str | None:
        original = getattr(exc, "orig", exc)
        return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
