from functools import lru_cache

from fastapi import Request

from data_control_service.adapters.registry import create_default_registry
from data_control_service.application.audit_service import InMemoryAuditService
from data_control_service.application.authorization_service import AuthorizationService
from data_control_service.application.context_resolver import ContextResolver
from data_control_service.application.data_control_service import DataControlService
from data_control_service.application.idempotency_service import InMemoryIdempotencyService
from data_control_service.application.routing_service import RoutingService
from data_control_service.config.settings import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_data_control_service() -> DataControlService:
    settings = get_settings()
    return DataControlService(
        context_resolver=ContextResolver(),
        authorization_service=AuthorizationService(),
        idempotency_service=InMemoryIdempotencyService(),
        routing_service=RoutingService(settings),
        adapter_registry=create_default_registry(),
        audit_service=InMemoryAuditService(),
    )


def get_request_id(request: Request) -> str | None:
    value = request.headers.get("x-request-id")
    return value if value else None
