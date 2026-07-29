from uuid import uuid4

from data_control_service.contracts.errors import ERROR_CATALOG


class DataControlError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: list[dict[str, object]] | None = None,
        incident_id: str | None = None,
    ) -> None:
        self.code = code
        self.spec = ERROR_CATALOG[code]
        self.message = message or self.spec.message
        self.details = details or []
        self.incident_id = incident_id or (
            f"inc_{uuid4().hex}" if self.spec.http_status >= 500 else None
        )
        super().__init__(self.message)
