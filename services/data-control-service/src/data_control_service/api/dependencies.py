from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import Request

from data_control_service.adapters.registry import create_default_registry
from data_control_service.application.audit_outbox_service import AuditOutboxService
from data_control_service.application.audit_service import InMemoryAuditService
from data_control_service.application.authorization_service import AuthorizationService
from data_control_service.application.context_resolver import ContextResolver
from data_control_service.application.data_control_service import DataControlService
from data_control_service.application.idempotency_service import IdempotencyService
from data_control_service.application.routing_service import RoutingService
from data_control_service.application.transaction_orchestrator import TransactionOrchestrator
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.policies import create_default_resource_registry
from data_control_service.infrastructure.auth.development_auth_provider import (
    DevelopmentAuthProvider,
)
from data_control_service.infrastructure.idempotency.in_memory import InMemoryIdempotencyRepository
from data_control_service.infrastructure.persistence.database import (
    DatabaseManager,
    require_database_url,
)
from data_control_service.infrastructure.persistence.repositories import (
    SQLAlchemyAuditOutboxRepository,
    SQLAlchemyAuditRepository,
    SQLAlchemyIdempotencyRepository,
    SQLAlchemyPolicyRepository,
    SQLAlchemyResourceMappingRepository,
)
from data_control_service.infrastructure.redis.manager import RedisManager
from data_control_service.infrastructure.resources.in_memory import (
    InMemoryResourceMappingRepository,
)
from data_control_service.ports.audit_repository import AuditRepository
from data_control_service.ports.auth_provider import AuthProvider
from data_control_service.ports.idempotency_repository import IdempotencyRepository
from data_control_service.ports.policy_repository import PolicyRepository
from data_control_service.ports.resource_mapping_repository import ResourceMappingRepository


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_control_database_manager() -> DatabaseManager | None:
    settings = get_settings()
    if not settings.control_database_url:
        if settings.app_env in {"production", "test"}:
            require_database_url(settings.control_database_url, "control", settings)
        return None
    return DatabaseManager(settings.control_database_url, settings, name="control")


@lru_cache
def get_target_postgresql_manager() -> DatabaseManager | None:
    settings = get_settings()
    if not settings.postgresql_adapter_database_url:
        if settings.postgresql_adapter_enabled or settings.app_env in {"production", "test"}:
            require_database_url(settings.postgresql_adapter_database_url, "target", settings)
        return None
    return DatabaseManager(
        settings.postgresql_adapter_database_url, settings, name="postgresql_adapter"
    )


@lru_cache
def get_redis_manager() -> RedisManager | None:
    settings = get_settings()
    if not settings.redis_adapter_enabled:
        return None
    if not settings.redis_url:
        if settings.redis_adapter_required or settings.app_env in {"production", "test"}:
            raise DataControlError("CONFIGURATION_INVALID", "REDIS_URL is required")
        return None
    return RedisManager(settings)


async def close_database_managers() -> None:
    control_database = get_control_database_manager()
    target_database = get_target_postgresql_manager()
    if control_database is not None:
        await control_database.close()
    if target_database is not None and target_database is not control_database:
        await target_database.close()
    redis_manager = get_redis_manager()
    if redis_manager is not None:
        await redis_manager.close()
    get_data_control_service.cache_clear()
    get_control_database_manager.cache_clear()
    get_target_postgresql_manager.cache_clear()
    get_redis_manager.cache_clear()


@lru_cache
def get_data_control_service() -> DataControlService:
    settings = get_settings()
    control_database = get_control_database_manager()
    target_database = get_target_postgresql_manager()
    redis_manager = get_redis_manager()
    audit_repository: AuditRepository | InMemoryAuditService
    if control_database is not None:
        resource_repository: ResourceMappingRepository = SQLAlchemyResourceMappingRepository(
            control_database.session_factory
        )
        policy_repository: PolicyRepository | None = SQLAlchemyPolicyRepository(
            control_database.session_factory
        )
        idempotency_repository: IdempotencyRepository = SQLAlchemyIdempotencyRepository(
            control_database.session_factory,
            processing_timeout_seconds=settings.idempotency_processing_timeout_seconds,
        )
        audit_repository = SQLAlchemyAuditRepository(control_database.session_factory)
        audit_outbox_repository = SQLAlchemyAuditOutboxRepository(control_database.session_factory)
        audit_service: AuditRepository | InMemoryAuditService | AuditOutboxService = (
            AuditOutboxService(audit_outbox_repository, settings)
        )
    else:
        resource_repository = InMemoryResourceMappingRepository(create_default_resource_registry())
        policy_repository = None
        idempotency_repository = InMemoryIdempotencyRepository()
        audit_repository = InMemoryAuditService()
        audit_service = audit_repository
    readiness_checks: dict[str, Callable[[], Awaitable[dict[str, str]]]] = {}
    if control_database is not None:
        readiness_checks["control_database"] = control_database.ping
        readiness_checks["control_migration"] = lambda: control_database.migration_current(
            schema="control_plane",
            expected_revision=settings.control_migration_head_revision,
        )
        readiness_checks["idempotency_repository"] = idempotency_repository.health
        readiness_checks["resource_mapping_repository"] = resource_repository.health
        if policy_repository is not None:
            readiness_checks["policy_provider"] = policy_repository.health
        if isinstance(audit_repository, SQLAlchemyAuditRepository):
            readiness_checks["audit_repository"] = audit_repository.health
        if control_database is not None:
            readiness_checks["audit_outbox_repository"] = audit_outbox_repository.health
    if target_database is not None:
        readiness_checks["postgresql_adapter_database"] = target_database.ping
        readiness_checks["target_migration"] = lambda: target_database.migration_current(
            schema="data_target",
            expected_revision=settings.target_migration_head_revision,
        )
    redis_client = None
    if redis_manager is not None:
        readiness_checks["redis_connection"] = redis_manager.ping

        async def redis_mapping_health() -> dict[str, str]:
            async_getter = getattr(resource_repository, "get_mapping_async", None)
            if async_getter is not None:
                mapping = await async_getter(
                    tenant_id="tenant_demo",
                    biz_domain="demo",
                    target=DataTarget.REDIS,
                    resource_type="CACHE_ENTRY",
                    logical_name="cache",
                )
            else:
                mapping = resource_repository.get_mapping(
                    tenant_id="tenant_demo",
                    biz_domain="demo",
                    target=DataTarget.REDIS,
                    resource_type="CACHE_ENTRY",
                    logical_name="cache",
                )
            return {"status": "ok" if mapping is not None else "error"}

        readiness_checks["redis_resource_mapping"] = redis_mapping_health
        redis_client = redis_manager.client()
    return DataControlService(
        context_resolver=ContextResolver(),
        authorization_service=AuthorizationService(policy_repository),
        idempotency_service=IdempotencyService(idempotency_repository, settings),
        routing_service=RoutingService(settings, resource_repository),
        transaction_orchestrator=TransactionOrchestrator(),
        adapter_registry=create_default_registry(
            settings,
            target_database.session_factory if target_database is not None else None,
            redis_client,
        ),
        audit_service=audit_service,
        readiness_checks=readiness_checks,
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
