from collections.abc import Awaitable, Callable
from time import perf_counter

from data_control_service.adapters.registry import AdapterRegistry
from data_control_service.application.audit_service import InMemoryAuditService
from data_control_service.application.authorization_service import AuthorizationService
from data_control_service.application.context_resolver import ContextResolver
from data_control_service.application.idempotency_service import IdempotencyService
from data_control_service.application.routing_service import RoutingService
from data_control_service.application.transaction_orchestrator import TransactionOrchestrator
from data_control_service.contracts.request import DataRequest
from data_control_service.contracts.response import DataResponse, PageInfo
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import (
    AdapterCommand,
    AdapterResult,
    ExecutionContext,
    RouteDecision,
)
from data_control_service.ports.audit_repository import AuditRepository
from data_control_service.ports.auth_provider import AuthenticatedPrincipal, RequestContext


class DataControlService:
    def __init__(
        self,
        *,
        context_resolver: ContextResolver,
        authorization_service: AuthorizationService,
        idempotency_service: IdempotencyService,
        routing_service: RoutingService,
        transaction_orchestrator: TransactionOrchestrator,
        adapter_registry: AdapterRegistry,
        audit_service: AuditRepository | InMemoryAuditService,
        readiness_checks: dict[str, Callable[[], Awaitable[dict[str, str]]]] | None = None,
    ) -> None:
        self._context_resolver = context_resolver
        self._authorization_service = authorization_service
        self._idempotency_service = idempotency_service
        self._routing_service = routing_service
        self._transaction_orchestrator = transaction_orchestrator
        self._adapter_registry = adapter_registry
        self._audit_service = audit_service
        self._readiness_checks = readiness_checks or {}

    async def dispatch(
        self,
        request: DataRequest,
        principal: AuthenticatedPrincipal,
        request_context: RequestContext,
    ) -> DataResponse:
        started = perf_counter()
        context = self._context_resolver.resolve(request, principal, request_context)
        route = None
        try:
            registration = await self._routing_service.get_registration(request, context)
            await self._authorization_service.authorize(request, context, registration)
            idempotency_record_id, replay = await self._idempotency_service.claim(request, context)
            if replay is not None:
                await self._record_access(
                    request, context, status="REPLAYED", code="OK", latency_ms=0
                )
                return replay

            route = self._routing_service.route(request, registration)
            adapter = self._adapter_registry.get_by_target(route.target)
            command = AdapterCommand(
                operation=request.operation,
                logical_resource=route.logical_resource,
                validated_payload={
                    "data": request.payload.data,
                    "query": request.payload.query,
                    "options": request.payload.options,
                    "resource_id": request.resource.resource_id,
                    "resource_mapping": route.resource_mapping,
                },
                scope=(context.tenant_id, context.biz_domain),
                timeout_ms=route.timeout_ms,
                route_id=route.route_id,
            )
            self._idempotency_service.adapter_execution_count += 1
            result = await self._transaction_orchestrator.execute(
                adapter=adapter,
                command=command,
                context=context,
                mode=route.transaction_mode,
            )
            duration_ms = round((perf_counter() - started) * 1000)
            response = DataResponse(
                request_id=context.request_id,
                trace_id=context.trace_id,
                success=True,
                code="OK",
                message="success",
                data=result.data,
                page=PageInfo(
                    limit=int(request.payload.options.get("limit", 50)),
                    cursor=result.cursor,
                    has_more=result.has_more,
                )
                if request.operation.value in {"LIST", "SEARCH"}
                else None,
                meta={
                    "adapter": adapter.name,
                    "route_id": route.route_id,
                    "duration_ms": duration_ms,
                    "affected_count": result.affected_count,
                    "resource_version": result.resource_version,
                    "idempotency_replayed": False,
                },
            )
            await self._idempotency_service.succeed(idempotency_record_id, request, response)
            await self._record_change(
                request, context, result, status="SUCCEEDED", code="OK", route=route
            )
            await self._record_access(
                request,
                context,
                status="SUCCEEDED",
                code="OK",
                latency_ms=duration_ms,
                route=route,
            )
            return response
        except DataControlError as exc:
            record_id = locals().get("idempotency_record_id")
            await self._idempotency_service.fail(record_id, request, exc.code)
            await self._record_access(
                request, context, status="FAILED", code=exc.code, latency_ms=0, route=route
            )
            raise

    async def _record_access(
        self,
        request: DataRequest,
        context: ExecutionContext,
        *,
        status: str,
        code: str,
        latency_ms: int,
        route: RouteDecision | None = None,
    ) -> None:
        if hasattr(self._audit_service, "record_access"):
            await self._audit_service.record_access(
                request, context, status=status, code=code, latency_ms=latency_ms, route=route
            )
            return
        await self._audit_service.record(request, context, status=status, code=code, route=route)

    async def _record_change(
        self,
        request: DataRequest,
        context: ExecutionContext,
        result: AdapterResult,
        *,
        status: str,
        code: str,
        route: RouteDecision,
    ) -> None:
        if hasattr(self._audit_service, "record_change"):
            await self._audit_service.record_change(
                request, context, result, status=status, code=code, route=route
            )

    async def readiness(self) -> dict[str, object]:
        registry_validation = await self._adapter_registry.validate()
        adapter_health = await self._adapter_registry.health_all()
        components: dict[str, object] = {
            "auth_provider": {"status": "ok"},
            "policy_provider": {"status": "ok"},
            "resource_mapping_repository": {"status": "ok"},
            "idempotency_repository": {"status": "ok"},
            "audit_repository": {"status": "ok"},
            "adapter_registry": {
                "status": registry_validation.status,
                "errors": list(registry_validation.errors),
            },
        }
        degraded = False
        ready = registry_validation.status == "ok"
        for name, check in self._readiness_checks.items():
            try:
                result = await check()
                components[name] = {"status": result.get("status", "ok")}
            except Exception:
                ready = False
                components[name] = {"status": "error"}
        for target, health in adapter_health.items():
            ok = health.status == "UP"
            if health.required and not ok:
                ready = False
            if not health.required and not ok:
                degraded = True
            components[target.value.lower()] = {
                "status": "ok" if ok else "error",
                "required": health.required,
            }
        return {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "degraded": degraded,
            "components": components,
        }
