import hashlib
import json
from datetime import UTC, datetime, timedelta

from data_control_service.config.settings import Settings
from data_control_service.contracts.request import DataRequest
from data_control_service.contracts.response import DataResponse
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext
from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimState,
    IdempotencyRepository,
    IdempotencyScope,
)


class IdempotencyService:
    def __init__(self, repository: IdempotencyRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings
        self.adapter_execution_count = 0

    def request_fingerprint(self, request: DataRequest) -> str:
        canonical = {
            "operation": request.operation.value,
            "target": request.resource.target.value,
            "resource": request.resource.model_dump(mode="json", exclude_none=True),
            "payload": request.payload.model_dump(mode="json"),
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def claim(
        self, request: DataRequest, context: ExecutionContext
    ) -> tuple[tuple[str, str] | None, DataResponse | None]:
        if not request.is_write:
            return None, None
        if not request.idempotency_key:
            raise DataControlError("IDEMPOTENCY_KEY_REQUIRED")
        result = await self._repository.claim(
            IdempotencyScope(
                tenant_id=context.tenant_id,
                biz_domain=context.biz_domain,
                operation=request.operation,
                target=request.resource.target,
                idempotency_key=request.idempotency_key,
            ),
            self.request_fingerprint(request),
            datetime.now(UTC) + timedelta(seconds=self._settings.idempotency_ttl_seconds),
        )
        if result.state == IdempotencyClaimState.CLAIMED:
            return (result.record_id, result.owner_token or ""), None
        if result.state == IdempotencyClaimState.REPLAY_SUCCEEDED and result.response_snapshot:
            replay = DataResponse.model_validate(result.response_snapshot)
            replay.meta["idempotency_replayed"] = True
            return None, replay
        if result.state == IdempotencyClaimState.FINGERPRINT_CONFLICT:
            raise DataControlError("IDEMPOTENCY_KEY_CONFLICT")
        if result.state == IdempotencyClaimState.IN_PROGRESS:
            raise DataControlError("IDEMPOTENCY_IN_PROGRESS")
        if result.state == IdempotencyClaimState.RECOVERY_REQUIRED:
            raise DataControlError("IDEMPOTENCY_RECOVERY_REQUIRED")
        if result.state == IdempotencyClaimState.RETRY_FAILED:
            return (result.record_id, result.owner_token or ""), None
        raise DataControlError("INTERNAL_ERROR")

    async def succeed(
        self, record_ref: tuple[str, str] | None, request: DataRequest, response: DataResponse
    ) -> None:
        if record_ref is None or not request.is_write:
            return
        record_id, owner_token = record_ref
        await self._repository.mark_succeeded(
            record_id, owner_token, response.model_dump(mode="json")
        )

    async def recovery_required(
        self,
        record_ref: tuple[str, str] | None,
        request: DataRequest,
        *,
        business_result_reference: dict[str, object],
        recovery_strategy: str,
        recovery_metadata: dict[str, object],
        error_code: str,
    ) -> None:
        if record_ref is None or not request.is_write:
            return
        record_id, owner_token = record_ref
        await self._repository.mark_recovery_required(
            record_id,
            owner_token,
            business_result_reference=business_result_reference,
            recovery_strategy=recovery_strategy,
            recovery_metadata=recovery_metadata,
            error_code=error_code,
            max_recovery_attempts=self._settings.idempotency_recovery_max_attempts,
        )

    async def fail(
        self, record_ref: tuple[str, str] | None, request: DataRequest, error_code: str
    ) -> None:
        if record_ref is None or not request.is_write:
            return
        record_id, owner_token = record_ref
        await self._repository.mark_failed(record_id, owner_token, error_code)
