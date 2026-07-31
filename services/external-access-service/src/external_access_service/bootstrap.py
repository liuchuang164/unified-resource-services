from dataclasses import dataclass

import httpx

from external_access_service.application.services.credential_manager import (
    EnvironmentCredentialManager,
)
from external_access_service.application.services.provider_router import ProviderRouter
from external_access_service.application.services.unified_entry import UnifiedExternalEntry
from external_access_service.audit.in_memory import InMemoryAuditSink
from external_access_service.domain.operations import OPERATIONS, OperationRegistry
from external_access_service.infrastructure.config import Settings
from external_access_service.infrastructure.providers.ali_farui import (
    AliFaruiAdapter,
    farui_mock_transport,
)
from external_access_service.interfaces.eag.gateway import ToolGateway
from external_access_service.security.fake import AuthorizationRule, FakePolicy, InMemoryRateLimiter


@dataclass(slots=True)
class Container:
    entry: UnifiedExternalEntry
    gateway: ToolGateway
    operations: OperationRegistry
    audit: InMemoryAuditSink
    policy: FakePolicy
    provider: AliFaruiAdapter


def build_container(
    settings: Settings | None = None,
    farui_client: httpx.AsyncClient | None = None,
) -> Container:
    settings = settings or Settings()
    operations = OperationRegistry()
    audit = InMemoryAuditSink()
    rules = tuple(
        AuthorizationRule(
            user_id=user,
            tenant_id="tenant_A",
            biz_domain="LEGAL",
            operation=operation.operation,
        )
        for user in ("user_001", "agent-user")
        for operation in OPERATIONS
    )
    policy = FakePolicy(rules)
    client = farui_client or httpx.AsyncClient(
        base_url=settings.farui_base_url,
        transport=farui_mock_transport() if settings.environment == "test" else None,
    )
    provider = AliFaruiAdapter(settings.farui_base_url, client=client)
    entry = UnifiedExternalEntry(
        operations=operations,
        router=ProviderRouter((provider,)),
        credential_manager=EnvironmentCredentialManager(settings),
        policy=policy,
        rate_limiter=InMemoryRateLimiter(),
        audit=audit,
    )
    return Container(
        entry=entry,
        gateway=ToolGateway(entry, operations),
        operations=operations,
        audit=audit,
        policy=policy,
        provider=provider,
    )
