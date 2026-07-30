from time import monotonic
from typing import Any, Literal

import structlog
from pydantic import ValidationError

from file_media_stream_service.application.dto.contracts import (
    ErrorDetail,
    UnifiedRequest,
    UnifiedResponse,
)
from file_media_stream_service.application.ports.protocols import (
    AuditSink,
    AuthorizationPolicy,
    CapabilityTokenVerifier,
    Clock,
    IdempotencyStore,
    IdentityVerifier,
    QuotaChecker,
    ReplayProtector,
)
from file_media_stream_service.application.use_cases.service import (
    UseCases,
    canonical_request_hash,
)
from file_media_stream_service.domain.entities.models import AuditEvent
from file_media_stream_service.domain.exceptions.errors import (
    DomainError,
    PermissionDenied,
)
from file_media_stream_service.entry.payloads import IDEMPOTENT_OPERATIONS, PAYLOAD_MODELS

logger = structlog.get_logger(__name__)


class UnsupportedApiVersion(DomainError):
    code = "UNSUPPORTED_API_VERSION"


class UnsupportedOperation(DomainError):
    code = "UNSUPPORTED_OPERATION"


class InvalidRequest(DomainError):
    code = "INVALID_REQUEST"


class UnifiedEntry:
    def __init__(
        self,
        use_cases: UseCases,
        identity: IdentityVerifier,
        capability: CapabilityTokenVerifier,
        authorization: AuthorizationPolicy,
        quota: QuotaChecker,
        replay: ReplayProtector,
        idempotency: IdempotencyStore,
        audit: AuditSink,
        clock: Clock,
        api_version: str = "v1",
    ) -> None:
        self.use_cases = use_cases
        self.identity = identity
        self.capability = capability
        self.authorization = authorization
        self.quota = quota
        self.replay = replay
        self.idempotency = idempotency
        self.audit = audit
        self.clock = clock
        self.api_version = api_version

    async def execute(
        self, request: UnifiedRequest, source: Literal["business", "gateway"] = "business"
    ) -> UnifiedResponse:
        started = monotonic()
        response: UnifiedResponse
        try:
            data = await self._execute(request, source)
            response = UnifiedResponse(
                request_id=request.context.request_id,
                trace_id=request.context.trace_id,
                success=True,
                data=data,
                error=None,
            )
        except DomainError as error:
            response = self._failure(request, error)
        except (KeyError, TypeError, ValueError, ValidationError):
            response = self._failure(request, InvalidRequest("Request payload is invalid"))
        except Exception:
            response = self._failure(request, DomainError("Internal service error"))
        await self._audit(request, response, int((monotonic() - started) * 1000))
        return response

    async def _execute(
        self, request: UnifiedRequest, source: Literal["business", "gateway"]
    ) -> dict[str, Any]:
        if request.api_version != self.api_version:
            raise UnsupportedApiVersion("API version is not supported")
        payload_model = PAYLOAD_MODELS.get(request.operation)
        if payload_model is None:
            raise UnsupportedOperation("Operation is not supported")
        context = request.context
        if context.caller_type == "agent" and source != "gateway":
            raise PermissionDenied("Agent callers must use the Tool Gateway")
        payload = payload_model.model_validate(request.payload).model_dump()
        await self.identity.verify(context)
        await self.capability.verify_capability(context, request.operation)
        resource_scope = self._resource_scope(payload)
        for action in self._authorization_actions(request.operation, payload):
            await self.authorization.authorize(context, action, resource_scope)
        await self.replay.check_and_record(context)
        request_hash = canonical_request_hash(payload)
        if request.operation in IDEMPOTENT_OPERATIONS:
            if not context.idempotency_key:
                raise InvalidRequest("idempotency_key is required for this operation")
            scope = (
                context.tenant_id,
                context.biz_domain,
                context.caller_id,
                request.operation,
                context.idempotency_key,
            )
            while True:
                decision, existing = await self.idempotency.reserve(scope, request_hash)
                if decision == "COMPLETED":
                    if existing is None:
                        raise DomainError("Completed idempotency record has no result")
                    return existing
                if decision == "WAIT":
                    await self.idempotency.wait(scope)
                    continue
                break
            try:
                await self.quota.check(context, request.operation)
                result = await self.use_cases.execute(request.operation, context, payload)
            except Exception:
                await self.idempotency.fail(scope)
                raise
            await self.idempotency.complete(scope, request_hash, result)
            return result
        await self.quota.check(context, request.operation)
        return await self.use_cases.execute(request.operation, context, payload)

    @staticmethod
    def _resource_scope(payload: dict[str, Any]) -> str | None:
        for key in ("resource_id", "input_resource_id", "session_id", "job_id"):
            if key in payload:
                return str(payload[key])
        return None

    @staticmethod
    def _authorization_actions(operation: str, payload: dict[str, Any]) -> tuple[str, ...]:
        if operation == "media.create_stream_session":
            direction = str(payload.get("direction", ""))
            data_actions = {
                "INGRESS": ("media_stream:publish",),
                "EGRESS": ("media_stream:subscribe",),
                "BIDIRECTIONAL": ("media_stream:publish", "media_stream:subscribe"),
            }
            return ("media_stream:create", *data_actions.get(direction, ()))
        if operation == "media.get_stream_session":
            return ("media_stream:subscribe",)
        if operation == "media.close_stream_session":
            return ("media_stream:close",)
        return (operation,)

    @staticmethod
    def _failure(request: UnifiedRequest, error: DomainError) -> UnifiedResponse:
        return UnifiedResponse(
            request_id=request.context.request_id,
            trace_id=request.context.trace_id,
            success=False,
            data=None,
            error=ErrorDetail(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            ),
        )

    async def _audit(
        self, request: UnifiedRequest, response: UnifiedResponse, duration_ms: int
    ) -> None:
        data = response.data or {}
        event = AuditEvent(
            audit_id=f"audit_{request.context.request_id}",
            request_id=request.context.request_id,
            trace_id=request.context.trace_id,
            tenant_id=request.context.tenant_id,
            biz_domain=request.context.biz_domain,
            caller_type=request.context.caller_type,
            caller_id=request.context.caller_id,
            operation=request.operation,
            resource_id=self._nested_id(data, "resource", "resource_id"),
            session_id=self._nested_id(data, "session", "session_id"),
            job_id=self._nested_id(data, "job", "job_id"),
            decision="ALLOW" if response.success else "DENY",
            result="SUCCESS" if response.success else "FAILURE",
            error_code=response.error.code if response.error else None,
            duration_ms=duration_ms,
            created_at=self.clock.now(),
        )
        try:
            await self.audit.write(event)
        except Exception:
            logger.error(
                "audit_write_failed",
                request_id=request.context.request_id,
                trace_id=request.context.trace_id,
                tenant_id=request.context.tenant_id,
                biz_domain=request.context.biz_domain,
                operation=request.operation,
            )
        logger.info(
            "operation_completed",
            request_id=request.context.request_id,
            trace_id=request.context.trace_id,
            tenant_id=request.context.tenant_id,
            biz_domain=request.context.biz_domain,
            caller_type=request.context.caller_type,
            caller_id=request.context.caller_id,
            operation=request.operation,
            decision="ALLOW" if response.success else "DENY",
            error_code=response.error.code if response.error else None,
            duration_ms=duration_ms,
            resource_id=event.resource_id,
            session_id=event.session_id,
            job_id=event.job_id,
        )

    @staticmethod
    def _nested_id(data: dict[str, Any], container: str, key: str) -> str | None:
        nested = data.get(container)
        return str(nested[key]) if isinstance(nested, dict) and key in nested else None
