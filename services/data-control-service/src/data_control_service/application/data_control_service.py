from time import perf_counter

from data_control_service.adapters.registry import AdapterRegistry
from data_control_service.application.audit_service import InMemoryAuditService
from data_control_service.application.authorization_service import AuthorizationService
from data_control_service.application.context_resolver import ContextResolver
from data_control_service.application.idempotency_service import InMemoryIdempotencyService
from data_control_service.application.routing_service import RoutingService
from data_control_service.contracts.request import DataRequest
from data_control_service.contracts.response import DataResponse, PageInfo
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand


class DataControlService:
    def __init__(
        self,
        *,
        context_resolver: ContextResolver,
        authorization_service: AuthorizationService,
        idempotency_service: InMemoryIdempotencyService,
        routing_service: RoutingService,
        adapter_registry: AdapterRegistry,
        audit_service: InMemoryAuditService,
    ) -> None:
        self._context_resolver = context_resolver
        self._authorization_service = authorization_service
        self._idempotency_service = idempotency_service
        self._routing_service = routing_service
        self._adapter_registry = adapter_registry
        self._audit_service = audit_service

    async def dispatch(self, request: DataRequest) -> DataResponse:
        started = perf_counter()
        context = self._context_resolver.resolve(request)
        route = None
        try:
            registration = self._routing_service.get_registration(request)
            self._authorization_service.authorize(request, context, registration)
            replay = await self._idempotency_service.claim(request, context)
            if replay is not None:
                await self._audit_service.record(request, context, status="REPLAYED", code="OK")
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
                },
                scope=(context.tenant_id, context.biz_domain),
                timeout_ms=route.timeout_ms,
                route_id=route.route_id,
            )
            result = await adapter.execute(command, context)
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
            await self._idempotency_service.succeed(request, context, response)
            await self._audit_service.record(
                request, context, status="SUCCEEDED", code="OK", route=route
            )
            return response
        except DataControlError as exc:
            await self._idempotency_service.fail(request, context, exc.spec.retryable)
            await self._audit_service.record(
                request, context, status="FAILED", code=exc.code, route=route
            )
            raise
