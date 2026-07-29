from typing import cast
from uuid import uuid4

from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import WRITE_OPERATIONS, TransactionMode
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import ExecutionContext, RouteDecision
from data_control_service.domain.policies import ResourceMapping
from data_control_service.ports.resource_mapping_repository import ResourceMappingRepository


class RoutingService:
    def __init__(self, settings: Settings, resource_repository: ResourceMappingRepository) -> None:
        self._settings = settings
        self._resource_repository = resource_repository

    async def get_registration(
        self, request: DataRequest, context: ExecutionContext
    ) -> ResourceMapping:
        async_getter = getattr(self._resource_repository, "get_mapping_async", None)
        if async_getter is not None:
            registration = cast(
                ResourceMapping | None,
                await async_getter(
                    tenant_id=context.tenant_id,
                    biz_domain=context.biz_domain,
                    target=request.resource.target,
                    resource_type=request.resource.type,
                    logical_name=request.resource.name,
                ),
            )
        else:
            registration = self._resource_repository.get_mapping(
                tenant_id=context.tenant_id,
                biz_domain=context.biz_domain,
                target=request.resource.target,
                resource_type=request.resource.type,
                logical_name=request.resource.name,
            )
        if registration is None:
            raise DataControlError("RESOURCE_TYPE_UNKNOWN")
        return registration

    def route(self, request: DataRequest, registration: ResourceMapping) -> RouteDecision:
        if request.operation not in registration.definition.allowed_operations:
            raise DataControlError("ROUTE_NOT_FOUND")
        transaction_mode = (
            request.transaction.mode if request.transaction else TransactionMode.LOCAL
        )
        if transaction_mode == TransactionMode.ATOMIC and request.resource.target.name not in {
            "POSTGRESQL",
            "NEO4J",
            "TIMESCALEDB",
        }:
            raise DataControlError("TRANSACTION_NOT_SUPPORTED")
        timeout_ms = min(
            request.timeout_ms or self._settings.default_timeout_ms, self._settings.max_timeout_ms
        )
        return RouteDecision(
            route_id=f"route_{uuid4().hex}",
            adapter_name=request.resource.target.value.lower(),
            target=request.resource.target,
            logical_resource=(
                f"{registration.definition.resource_type}:{registration.definition.logical_name}"
            ),
            read_write_mode="WRITE" if request.operation in WRITE_OPERATIONS else "READ",
            timeout_ms=timeout_ms,
            transaction_mode=transaction_mode,
            policy_version="phase1-static-v1",
            resource_mapping=registration,
        )
