from functools import lru_cache

from fastapi import Request

from data_control_service.adapters.registry import create_default_registry
from data_control_service.application.audit_service import InMemoryAuditService
from data_control_service.application.authorization_service import AuthorizationService
from data_control_service.application.context_resolver import ContextResolver
from data_control_service.application.data_control_service import DataControlService
from data_control_service.application.idempotency_service import IdempotencyService
from data_control_service.application.routing_service import RoutingService
from data_control_service.application.transaction_orchestrator import TransactionOrchestrator
from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.policies import create_default_resource_registry
from data_control_service.infrastructure.auth.development_auth_provider import (
    DevelopmentAuthProvider,
)
from data_control_service.infrastructure.idempotency.in_memory import InMemoryIdempotencyRepository
from data_control_service.infrastructure.resources.in_memory import (
    InMemoryResourceMappingRepository,
)
from data_control_service.ports.auth_provider import AuthProvider


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_data_control_service() -> DataControlService:
    settings = get_settings()
    resource_repository = InMemoryResourceMappingRepository(create_default_resource_registry())
    return DataControlService(
        context_resolver=ContextResolver(),
        authorization_service=AuthorizationService(),
        idempotency_service=IdempotencyService(InMemoryIdempotencyRepository(), settings),
        routing_service=RoutingService(settings, resource_repository),
        transaction_orchestrator=TransactionOrchestrator(),
        adapter_registry=create_default_registry(settings),
        audit_service=InMemoryAuditService(),
    )


@lru_cache
def get_auth_provider() -> AuthProvider:
    settings = get_settings()
    if settings.auth_provider == "development":
        return DevelopmentAuthProvider(settings)
    raise DataControlError("CONFIGURATION_INVALID", "unknown auth provider")


def get_request_id(request: Request) -> str | None:
    value = request.headers.get("x-request-id")
    return value if value else None
