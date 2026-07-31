from datetime import UTC, datetime
from typing import Any

import jwt

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.ports.auth_provider import (
    AuthenticatedPrincipal,
    AuthenticationCredential,
    RequestContext,
)


class CapabilityTokenAuthProvider:
    def __init__(self, settings: Settings) -> None:
        self._algorithm = settings.capability_token_algorithm.upper()
        if self._algorithm not in {"HS256", "RS256", "ES256"}:
            raise DataControlError(
                "CONFIGURATION_INVALID",
                "capability token algorithm is not supported",
            )
        self._issuer = settings.capability_token_issuer
        self._audience = settings.capability_token_audience
        if settings.app_env.lower() == "production" and self._algorithm.startswith("HS"):
            raise DataControlError(
                "CONFIGURATION_INVALID",
                "symmetric capability tokens are not allowed in production",
            )
        verification_key = (
            settings.capability_token_public_key
            if self._algorithm.startswith(("RS", "ES", "PS", "ED"))
            else settings.capability_token_shared_secret
        )
        if not verification_key:
            raise DataControlError(
                "CONFIGURATION_INVALID",
                "capability token verification key is required",
            )
        self._verification_key = verification_key.replace("\\n", "\n")

    async def authenticate(
        self,
        credential: AuthenticationCredential,
        request_context: RequestContext,
    ) -> AuthenticatedPrincipal:
        token = _bearer_token(credential.headers)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._verification_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "jti",
                        "sub",
                        "tenant_id",
                        "biz_domain",
                        "session_id",
                        "task_id",
                        "allowed_tools",
                        "allowed_actions",
                    ]
                },
            )
        except jwt.PyJWTError as exc:
            raise DataControlError("AUTH_TOKEN_INVALID") from exc

        subject_id = _claim_string(claims, "sub")
        tenant_id = _claim_string(claims, "tenant_id")
        biz_domain = _claim_string(claims, "biz_domain")
        subject_type = str(claims.get("subject_type") or "AGENT")
        if subject_type != "AGENT":
            raise DataControlError("AUTH_TOKEN_INVALID")
        return AuthenticatedPrincipal(
            subject_id=subject_id,
            subject_type=subject_type,
            tenant_id=tenant_id,
            allowed_biz_domains=(biz_domain,),
            roles=_claim_strings(claims, "roles"),
            permissions=_claim_strings(claims, "permissions"),
            credential_source="capability-token",
            authenticated_at=datetime.now(UTC),
            session_id=_claim_string(claims, "session_id"),
            task_id=_claim_string(claims, "task_id"),
            allowed_tools=_claim_strings(claims, "allowed_tools"),
            allowed_actions=_claim_strings(claims, "allowed_actions"),
        )


def _bearer_token(headers: dict[str, str]) -> str:
    normalized = {key.lower(): value for key, value in headers.items()}
    authorization = normalized.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise DataControlError("AUTH_REQUIRED")
    return token


def _claim_string(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise DataControlError("AUTH_TOKEN_INVALID")
    return value


def _claim_strings(claims: dict[str, Any], name: str) -> tuple[str, ...]:
    value = claims.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DataControlError("AUTH_TOKEN_INVALID")
    return tuple(value)
