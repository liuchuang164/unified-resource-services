import asyncio
from time import monotonic

import structlog

from external_access_service.application.audit import AuditEventPublisher, SyncAuditEventPublisher
from external_access_service.application.governance.retry import RetryPolicyService
from external_access_service.application.ports.protocols import (
    AuditSinkPort,
    CircuitBreakerPort,
    CredentialManagerPort,
    PolicyPort,
    QuotaPort,
    RateLimiterPort,
    UsageMeterPort,
)
from external_access_service.application.services.provider_router import ProviderRouter
from external_access_service.domain.errors import (
    BizDomainScopeMismatch,
    DomainError,
    ErrorCode,
    OperationNotAllowed,
    TenantScopeMismatch,
)
from external_access_service.domain.models import (
    DispatchStatus,
    ErrorDetail,
    ExternalDispatchRequest,
    ExternalDispatchResponse,
    ProviderCode,
    ProviderRef,
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
        quota: QuotaPort | None = None,
        usage_meter: UsageMeterPort | None = None,
        audit_publisher: AuditEventPublisher | None = None,
        circuit_breaker: CircuitBreakerPort | None = None,
        retry_policy: RetryPolicyService | None = None,
    ) -> None:
        self.operations = operations
        self.router = router
        self.credential_manager = credential_manager
        self.policy = policy
        self.rate_limiter = rate_limiter
        self.audit = audit
        self.audit_publisher = audit_publisher or SyncAuditEventPublisher(audit)
        self.quota = quota
        self.usage_meter = usage_meter
        self.circuit_breaker = circuit_breaker
        self.retry_policy = retry_policy or RetryPolicyService()

    async def dispatch(self, request: ExternalDispatchRequest) -> ExternalDispatchResponse:
        started = monotonic()
        retry_count = 0
        retry_reason: str | None = None
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
            if self.quota is not None:
                await self.quota.check(request)
            providers = self.router.resolve_candidates(request)
            attempts = request.policy.retry.max_attempts if request.policy.retry.enabled else 1
            last_error: DomainError | None = None
            for provider in providers:
                provider_request = self._with_provider(request, provider.provider_code())
                if not provider.supports(provider_request.operation):
                    last_error = OperationNotAllowed("Provider does not support operation")
                    continue
                credential = await self.credential_manager.resolve(provider_request)
                if self.circuit_breaker is not None:
                    await self.circuit_breaker.before_call(provider.provider_code())
                for attempt in range(1, attempts + 1):
                    retry_count = attempt - 1
                    try:
                        result = await asyncio.wait_for(
                            provider.execute(provider_request, credential),
                            timeout=provider_request.policy.timeout_ms / 1000,
                        )
                        provider_request_id = result.provider_request_id
                        response = self._success(
                            provider_request, result, started, provider_request_id
                        )
                        if self.circuit_breaker is not None:
                            await self.circuit_breaker.record_success(provider.provider_code())
                        if self.quota is not None:
                            await self.quota.record(provider_request)
                        if self.usage_meter is not None:
                            await self.usage_meter.record_usage(provider_request, response)
                        await self._record_audit(
                            response, provider_request, retry_count, retry_reason
                        )
                        return response
                    except DomainError as error:
                        last_error = error
                        if self.circuit_breaker is not None:
                            await self.circuit_breaker.record_failure(
                                provider.provider_code(), error
                            )
                        decision = self.retry_policy.decide(error, attempt, attempts)
                        retry_reason = decision.reason
                        if not decision.should_retry:
                            break
                        await asyncio.sleep(decision.delay_seconds)
                    except TimeoutError:
                        from external_access_service.domain.errors import ProviderTimeout

                        timeout_error = ProviderTimeout("Provider request timed out")
                        last_error = timeout_error
                        if self.circuit_breaker is not None:
                            await self.circuit_breaker.record_failure(
                                provider.provider_code(), timeout_error
                            )
                        decision = self.retry_policy.decide(timeout_error, attempt, attempts)
                        retry_reason = decision.reason
                        if not decision.should_retry:
                            break
                        await asyncio.sleep(decision.delay_seconds)
                if last_error is not None and not last_error.retryable:
                    raise last_error
            if last_error is not None:
                raise last_error
            raise RuntimeError("Retry loop exited unexpectedly")
        except DomainError as error:
            response = self._failure(request, error, started, provider_request_id, retry_count)
            await self._record_audit(response, request, retry_count, retry_reason)
            return response
        except Exception:
            response = self._failure(
                request,
                DomainError("Internal service error"),
                started,
                provider_request_id,
                retry_count,
            )
            await self._record_audit(response, request, retry_count, retry_reason)
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
        self,
        response: ExternalDispatchResponse,
        request: ExternalDispatchRequest,
        retry_count: int,
        retry_reason: str | None,
    ) -> None:
        event = {
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
            "status": response.status.value,
            "error_code": response.error.code if response.error else None,
            "latency_ms": response.latency_ms,
            "retry_count": retry_count,
            "retry_reason": retry_reason,
            "provider_request_id": response.provider_request_id,
            "estimated_usage": response.usage.model_dump(),
            "estimated_cost": response.usage.estimated_cost,
            "payload_summary": redact({"keys": sorted(request.payload.keys())}),
        }
        try:
            await self.audit_publisher.publish(event)
        except Exception:
            logger.error(
                "audit_publish_uncaught_failure",
                request_id=request.request_id,
                trace_id=request.trace_id,
                tenant_id=request.auth_context.tenant_id,
                biz_domain=request.biz_context.biz_domain,
                operation=request.operation,
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

    @staticmethod
    def _with_provider(
        request: ExternalDispatchRequest, provider_code: ProviderCode
    ) -> ExternalDispatchRequest:

        return request.model_copy(
            update={
                "provider": ProviderRef(
                    provider_code=provider_code,
                    capability=request.provider.capability,
                )
            }
        )

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
