from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from data_control_service.domain.exceptions import DataControlError


class PostgreSQLErrorMapper:
    @staticmethod
    def to_error(exc: Exception) -> DataControlError:
        if isinstance(exc, DataControlError):
            return exc
        if isinstance(exc, SQLAlchemyTimeoutError):
            return DataControlError("ADAPTER_TIMEOUT")
        if isinstance(exc, OperationalError):
            return DataControlError("ADAPTER_UNAVAILABLE")
        if isinstance(exc, IntegrityError):
            sqlstate = PostgreSQLErrorMapper._sqlstate(exc)
            if sqlstate == "23505":
                return DataControlError("DATA_CONSTRAINT_VIOLATION")
            if sqlstate in {"23503", "23514", "23502"}:
                return DataControlError("DATA_CONSTRAINT_VIOLATION")
            if sqlstate in {"40001", "40P01"}:
                return DataControlError("TRANSACTION_ROLLED_BACK")
            return DataControlError("DATA_CONSTRAINT_VIOLATION")
        sqlstate = PostgreSQLErrorMapper._sqlstate(exc)
        if sqlstate in {"57014"}:
            return DataControlError("ADAPTER_TIMEOUT")
        if sqlstate in {"08000", "08003", "08006", "53300"}:
            return DataControlError("ADAPTER_UNAVAILABLE")
        if sqlstate in {"40001", "40P01"}:
            return DataControlError("TRANSACTION_ROLLED_BACK")
        return DataControlError("INTERNAL_ERROR")

    @staticmethod
    def _sqlstate(exc: Exception) -> str | None:
        original = getattr(exc, "orig", exc)
        return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
