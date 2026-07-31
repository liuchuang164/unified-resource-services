import asyncio
from time import monotonic

import structlog

from external_access_service.application.ports.protocols import (
    AuditSinkPort,
    CredentialManagerPort,
    PolicyPort,
    RateLimiterPort,
)
from external_access_service.application.services.provider_router import ProviderRouter
from external_access_service.domain.errors import (
    BizDomainScopeMismatch,
    DomainError,
    ErrorCode,
    OperationNotAllowed,
    ProviderRateLimited,
    TenantScopeMismatch,
)
from external_access_service.domain.models import (
    DispatchStatus,
    ErrorDetail,
    ExternalDispatchRequest,
    ExternalDispatchResponse,
)
from external_access_service.domain.operations import OperationRegistry
from external_access_service.infrastructure.observability.redaction import redact

logger = structlog.get_logger(__name__)


class UnifiedExternalEntry:
    def __init__(
        self,
        operations: OperationRegistry,
        router: ProviderRouter,
        credential_manager: CredentialManagerPort,
        policy: PolicyPort,
        rate_limiter: RateLimiterPort,
        audit: AuditSinkPort,
    ) -> None:
        self.operations = operations
        self.router = router
        self.credential_manager = credential_manager
        self.policy = policy
        self.rate_limiter = rate_limiter
        self.audit = audit

    async def dispatch(self, request: ExternalDispatchRequest) -> ExternalDispatchResponse:
        started = monotonic()
        retry_count = 0
        provider_request_id: str | None = None
        try:
            operation = self.operations.get(request.operation)
            if request.provider.provider_code != operation.provider_code:
                raise OperationNotAllowed("Operation is not allowed for requested provider")
            if request.biz_context.biz_domain not in operation.allowed_biz_domains:
                raise BizDomainScopeMismatch("Operation is not allowed for this business domain")
            self._reject_body_scope_conflicts(request)
            self._validate_payload_schema(request.payload)
            await self.policy.authorize(request)
            await self.rate_limiter.check(request)
            provider = self.router.resolve(request.provider.provider_code)
            if not provider.supports(request.operation):
                raise OperationNotAllowed("Provider does not support operation")
            credential = await self.credential_manager.resolve(request)
            attempts = request.policy.retry.max_attempts if request.policy.retry.enabled else 1
            for attempt in range(1, attempts + 1):
                retry_count = attempt - 1
                try:
                    result = await asyncio.wait_for(
                        provider.execute(request, credential),
                        timeout=request.policy.timeout_ms / 1000,
                    )
                    provider_request_id = result.provider_request_id
                    response = self._success(request, result, started, provider_request_id)
                    await self._record_audit(response, request, retry_count)
                    return response
                except DomainError as error:
                    if not self._should_retry(error, attempt, attempts):
                        raise
                    await asyncio.sleep(min(0.05 * (2 ** (attempt - 1)), 0.2))
                except TimeoutError as exc:
                    from external_access_service.domain.errors import ProviderTimeout

                    timeout_error = ProviderTimeout("Provider request timed out")
                    if not self._should_retry(timeout_error, attempt, attempts):
                        raise timeout_error from exc
                    await asyncio.sleep(min(0.05 * (2 ** (attempt - 1)), 0.2))
            raise RuntimeError("Retry loop exited unexpectedly")
        except DomainError as error:
            response = self._failure(request, error, started, provider_request_id, retry_count)
            await self._record_audit(response, request, retry_count)
            return response
        except Exception:
            response = self._failure(
                request,
                DomainError("Internal service error"),
                started,
                provider_request_id,
                retry_count,
            )
            await self._record_audit(response, request, retry_count)
            return response
        finally:
            logger.info(
                "external_dispatch_completed",
                request_id=request.request_id,
                trace_id=request.trace_id,
                tenant_id=request.auth_context.tenant_id,
                biz_domain=request.biz_context.biz_domain,
                operation=request.operation,
                provider=request.provider.provider_code.value,
                retry_count=retry_count,
            )

    async def _record_audit(
        self, response: ExternalDispatchResponse, request: ExternalDispatchRequest, retry_count: int
    ) -> None:
        await self.audit.write(
            {
                "audit_id": f"audit_{request.request_id}",
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "tenant_id": request.auth_context.tenant_id,
                "biz_domain": request.biz_context.biz_domain,
                "caller_type": request.request_source.value,
                "caller_id": request.caller_id or request.auth_context.user_id,
                "agent_id": request.agent_id,
                "tool_call_id": request.tool_call_id,
                "operation": request.operation,
                "provider": request.provider.provider_code.value,
                "result_status": response.status.value,
                "error_code": response.error.code if response.error else None,
                "retry_count": retry_count,
                "provider_request_id": response.provider_request_id,
                "estimated_usage": response.usage.model_dump(),
                "estimated_cost": response.usage.estimated_cost,
                "payload_summary": redact({"keys": sorted(request.payload.keys())}),
            }
        )

    def _success(
        self,
        request: ExternalDispatchRequest,
        result: object,
        started: float,
        provider_request_id: str | None,
    ) -> ExternalDispatchResponse:
        from external_access_service.domain.models import ProviderResult

        typed = (
            result
            if isinstance(result, ProviderResult)
            else ProviderResult.model_validate(result)
        )
        response = ExternalDispatchResponse(
            request_id=request.request_id,
            trace_id=request.trace_id,
            tenant_id=request.auth_context.tenant_id,
            biz_domain=request.biz_context.biz_domain,
            operation=request.operation,
            provider=request.provider.provider_code,
            status=DispatchStatus.SUCCEEDED,
            data=typed.data,
            usage=typed.usage,
            latency_ms=int((monotonic() - started) * 1000),
            provider_request_id=provider_request_id,
            error=None,
        )
        return response

    def _failure(
        self,
        request: ExternalDispatchRequest,
        error: DomainError,
        started: float,
        provider_request_id: str | None,
        retry_count: int,
    ) -> ExternalDispatchResponse:
        response = ExternalDispatchResponse(
            request_id=request.request_id,
            trace_id=request.trace_id,
            tenant_id=request.auth_context.tenant_id,
            biz_domain=request.biz_context.biz_domain,
            operation=request.operation,
            provider=request.provider.provider_code,
            status=DispatchStatus.FAILED,
            data=None,
            latency_ms=int((monotonic() - started) * 1000),
            provider_request_id=provider_request_id,
            error=ErrorDetail(
                code=error.code.value if isinstance(error.code, ErrorCode) else str(error.code),
                message=error.message,
                retryable=error.retryable,
                details=redact(error.details),
            ),
        )
        return response

    @staticmethod
    def _should_retry(error: DomainError, attempt: int, attempts: int) -> bool:
        return attempt < attempts and (
            error.retryable or isinstance(error, ProviderRateLimited)
        )

    @staticmethod
    def _reject_body_scope_conflicts(request: ExternalDispatchRequest) -> None:
        tenant = request.payload.get("tenant_id")
        biz_domain = request.payload.get("biz_domain")
        if tenant is not None and tenant != request.auth_context.tenant_id:
            raise TenantScopeMismatch("Payload tenant_id conflicts with trusted context")
        if biz_domain is not None and biz_domain != request.biz_context.biz_domain:
            raise BizDomainScopeMismatch("Payload biz_domain conflicts with trusted context")

    @staticmethod
    def _validate_payload_schema(payload: dict[str, object]) -> None:
        allowed = {"query", "limit"}
        unknown = set(payload) - allowed
        if unknown:
            from external_access_service.domain.errors import InvalidRequest

            raise InvalidRequest(
                "Request payload contains unsupported fields",
                {"fields": sorted(unknown)},
            )
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            from external_access_service.domain.errors import InvalidRequest

            raise InvalidRequest("query is required")
        limit = payload.get("limit")
        if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > 50):
            from external_access_service.domain.errors import InvalidRequest

            raise InvalidRequest("limit must be between 1 and 50")
