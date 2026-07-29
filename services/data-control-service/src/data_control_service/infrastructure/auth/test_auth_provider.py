from datetime import UTC, datetime

from data_control_service.ports.auth_provider import (
    AuthenticatedPrincipal,
    AuthenticationCredential,
    RequestContext,
)


class TestAuthProvider:
    def __init__(
        self,
        *,
        subject_id: str = "svc_demo",
        tenant_id: str = "tenant_demo",
        biz_domains: tuple[str, ...] = ("demo",),
        roles: tuple[str, ...] = (),
        permissions: tuple[str, ...] = (),
    ) -> None:
        self._principal = AuthenticatedPrincipal(
            subject_id=subject_id,
            subject_type="SERVICE",
            tenant_id=tenant_id,
            allowed_biz_domains=biz_domains,
            roles=roles,
            permissions=permissions,
            credential_source="test",
            authenticated_at=datetime.now(UTC),
        )

    async def authenticate(
        self,
        credential: AuthenticationCredential,
        request_context: RequestContext,
    ) -> AuthenticatedPrincipal:
        return self._principal
