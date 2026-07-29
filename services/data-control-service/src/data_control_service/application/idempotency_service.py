import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from data_control_service.contracts.request import DataRequest
from data_control_service.contracts.response import DataResponse
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass
class IdempotencyRecord:
    digest: str
    status: IdempotencyStatus
    response: DataResponse | None = None


class InMemoryIdempotencyService:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str, str], IdempotencyRecord] = {}

    def request_digest(self, request: DataRequest) -> str:
        canonical = request.model_dump(
            mode="json",
            exclude={"trace_id", "metadata"},
            exclude_none=True,
        )
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def claim(self, request: DataRequest, context: ExecutionContext) -> DataResponse | None:
        if not request.is_write:
            return None
        if not request.idempotency_key:
            raise DataControlError("IDEMPOTENCY_KEY_REQUIRED")
        key = (
            context.tenant_id,
            context.biz_domain,
            context.subject_id,
            request.operation.value,
            request.idempotency_key,
        )
        digest = self.request_digest(request)
        record = self._records.get(key)
        if record is None:
            self._records[key] = IdempotencyRecord(
                digest=digest, status=IdempotencyStatus.PROCESSING
            )
            return None
        if record.digest != digest:
            raise DataControlError("IDEMPOTENCY_KEY_CONFLICT")
        if record.status == IdempotencyStatus.PROCESSING:
            raise DataControlError("IDEMPOTENCY_IN_PROGRESS")
        if record.status == IdempotencyStatus.SUCCEEDED and record.response is not None:
            replay = record.response.model_copy(deep=True)
            replay.meta["idempotency_replayed"] = True
            return replay
        return None

    async def succeed(
        self, request: DataRequest, context: ExecutionContext, response: DataResponse
    ) -> None:
        if not request.is_write or not request.idempotency_key:
            return
        key = (
            context.tenant_id,
            context.biz_domain,
            context.subject_id,
            request.operation.value,
            request.idempotency_key,
        )
        self._records[key] = IdempotencyRecord(
            digest=self.request_digest(request),
            status=IdempotencyStatus.SUCCEEDED,
            response=response.model_copy(deep=True),
        )

    async def fail(self, request: DataRequest, context: ExecutionContext, retryable: bool) -> None:
        if not request.is_write or not request.idempotency_key:
            return
        key = (
            context.tenant_id,
            context.biz_domain,
            context.subject_id,
            request.operation.value,
            request.idempotency_key,
        )
        record = self._records.get(key)
        if record is not None:
            record.status = (
                IdempotencyStatus.FAILED_RETRYABLE if retryable else IdempotencyStatus.FAILED_FINAL
            )
