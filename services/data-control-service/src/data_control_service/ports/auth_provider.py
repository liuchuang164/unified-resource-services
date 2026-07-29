from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuthenticationCredential:
    headers: dict[str, str]


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    trace_id: str | None
    source: str
    client_host: str | None = None


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject_id: str
    subject_type: str
    tenant_id: str
    allowed_biz_domains: tuple[str, ...]
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    credential_source: str
    authenticated_at: datetime


class AuthProvider(Protocol):
    async def authenticate(
        self,
        credential: AuthenticationCredential,
        request_context: RequestContext,
    ) -> AuthenticatedPrincipal: ...
