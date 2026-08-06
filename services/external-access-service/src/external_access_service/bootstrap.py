from dataclasses import dataclass

import httpx

from external_access_service.application.context import ContextResolver
from external_access_service.application.governance import (
    PolicyRule,
    PolicyService,
    QuotaRule,
    QuotaService,
    UsageMeterService,
)
from external_access_service.application.security import CapabilityVerifier
from external_access_service.application.services.credential_manager import (
    EnvironmentCredentialManager,
)
from external_access_service.application.services.credential_provider import (
    EnvironmentCredentialProvider,
)
from external_access_service.application.services.provider_router import ProviderRouter
from external_access_service.application.services.unified_entry import UnifiedExternalEntry
from external_access_service.domain.models import ProviderCode
from external_access_service.domain.operations import OPERATIONS, OperationRegistry
from external_access_service.infrastructure.config import Settings
from external_access_service.infrastructure.persistence import (
    PersistentAuditRepository,
    UsageRepository,
)
from external_access_service.infrastructure.providers.ali_farui import (
    AliFaruiAdapter,
    farui_mock_transport,
)
from external_access_service.interfaces.eag.gateway import ToolGateway
from external_access_service.security.fake import InMemoryRateLimiter


@dataclass(slots=True)
class Container:
    entry: UnifiedExternalEntry
    gateway: ToolGateway
    operations: OperationRegistry
    audit: PersistentAuditRepository
    usage_repository: UsageRepository
    usage_meter: UsageMeterService
    quota: QuotaService
    policy: PolicyService
    context_resolver: ContextResolver
    capability: CapabilityVerifier
    provider: AliFaruiAdapter


def build_container(
    settings: Settings | None = None,
    farui_client: httpx.AsyncClient | None = None,
) -> Container:
    settings = settings or Settings()
    operations = OperationRegistry()
    audit = PersistentAuditRepository()
    usage_repository = UsageRepository()
    usage_meter = UsageMeterService(usage_repository)
    quota = QuotaService(
        (
            QuotaRule(
                tenant_id="tenant_A",
                biz_domain="LEGAL",
                operation="ALI_FARUI_LEGAL_RESEARCH_FULL",
                provider=ProviderCode.ALI_FARUI,
                daily_limit=100,
            ),
        )
    )
    rules = tuple(
        PolicyRule(
            tenant_id="tenant_A",
            biz_domain="LEGAL",
            operation=operation.operation,
            role=role,
        )
        for role in ("LAWYER", "AGENT")
        for operation in OPERATIONS
    )
    policy = PolicyService(rules)
    capability = CapabilityVerifier(settings.capability_secret, issuer=settings.capability_issuer)
    context_resolver = ContextResolver(
        allow_legacy_body_context=settings.allow_legacy_body_context
    )
    client = farui_client or httpx.AsyncClient(
        base_url=settings.farui_base_url,
        transport=farui_mock_transport() if settings.environment == "test" else None,
    )
    provider = AliFaruiAdapter(settings.farui_base_url, client=client)
    entry = UnifiedExternalEntry(
        operations=operations,
        router=ProviderRouter((provider,)),
        credential_manager=EnvironmentCredentialManager(
            EnvironmentCredentialProvider(settings)
        ),
        policy=policy,
        rate_limiter=InMemoryRateLimiter(),
        audit=audit,
        quota=quota,
        usage_meter=usage_meter,
    )
    return Container(
        entry=entry,
        gateway=ToolGateway(entry, operations, capability),
        operations=operations,
        audit=audit,
        usage_repository=usage_repository,
        usage_meter=usage_meter,
        quota=quota,
        policy=policy,
        context_resolver=context_resolver,
        capability=capability,
        provider=provider,
    )
