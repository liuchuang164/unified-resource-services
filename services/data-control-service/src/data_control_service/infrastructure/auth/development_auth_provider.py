import re
from datetime import UTC, datetime

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.ports.auth_provider import (
    AuthenticatedPrincipal,
    AuthenticationCredential,
    RequestContext,
)

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{2,128}$")


class DevelopmentAuthProvider:
    def __init__(self, settings: Settings) -> None:
        if settings.app_env.lower() == "production":
            raise DataControlError(
                "CONFIGURATION_INVALID",
                "DevelopmentAuthProvider cannot be enabled in production",
            )
        self._settings = settings

    async def authenticate(
        self,
        credential: AuthenticationCredential,
        request_context: RequestContext,
    ) -> AuthenticatedPrincipal:
        headers = {key.lower(): value for key, value in credential.headers.items()}
        subject_id = headers.get("x-dev-subject-id")
        tenant_id = headers.get("x-dev-tenant-id")
        biz_domains = _split_header(headers.get("x-dev-biz-domains"))
        if not subject_id or not tenant_id or not biz_domains:
            raise DataControlError("AUTH_REQUIRED")
        _validate_token("subject", subject_id)
        _validate_token("tenant", tenant_id)
        for domain in biz_domains:
            _validate_token("biz_domain", domain)
        roles = tuple(_split_header(headers.get("x-dev-roles")))
        permissions = tuple(_split_header(headers.get("x-dev-permissions")))
        for value in (*roles, *permissions):
            _validate_token("role_or_permission", value)
        return AuthenticatedPrincipal(
            subject_id=subject_id,
            subject_type=headers.get("x-dev-subject-type", "SERVICE"),
            tenant_id=tenant_id,
            allowed_biz_domains=tuple(biz_domains),
            roles=roles,
            permissions=permissions,
            credential_source="development-header",
            authenticated_at=datetime.now(UTC),
        )


def _split_header(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_token(name: str, value: str) -> None:
    if not _TOKEN_PATTERN.match(value):
        raise DataControlError("AUTH_TOKEN_INVALID", f"invalid {name} claim")
