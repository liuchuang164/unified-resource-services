from dataclasses import dataclass
from typing import Any

import jwt

from data_access_gateway.config import Settings
from data_access_gateway.errors import GatewayError


@dataclass(frozen=True)
class CapabilityPrincipal:
    agent_id: str
    tenant_id: str
    biz_domain: str
    session_id: str
    task_id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_actions: tuple[str, ...]

    def authorize(self, tool_name: str, action: str) -> None:
        if tool_name not in self.allowed_tools:
            raise GatewayError("CAPABILITY_SCOPE_DENIED")
        if f"{tool_name}:{action}" not in self.allowed_actions:
            raise GatewayError("CAPABILITY_SCOPE_DENIED")


class CapabilityTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._algorithm = settings.capability_token_algorithm.upper()
        self._issuer = settings.capability_token_issuer
        self._audience = settings.capability_token_audience
        verification_key = (
            settings.capability_token_public_key
            if self._algorithm.startswith(("RS", "ES", "PS", "ED"))
            else settings.capability_token_shared_secret
        )
        if not verification_key:
            raise ValueError("capability token verification key is required")
        self._verification_key = verification_key.replace("\\n", "\n")

    def verify_authorization(self, authorization: str | None) -> tuple[str, CapabilityPrincipal]:
        if not authorization:
            raise GatewayError("CAPABILITY_TOKEN_REQUIRED")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise GatewayError("CAPABILITY_TOKEN_REQUIRED")
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
                    ]
                },
            )
        except jwt.PyJWTError as exc:
            raise GatewayError("CAPABILITY_TOKEN_INVALID") from exc
        return token, CapabilityPrincipal(
            agent_id=_string_claim(claims, "sub"),
            tenant_id=_string_claim(claims, "tenant_id"),
            biz_domain=_string_claim(claims, "biz_domain"),
            session_id=_string_claim(claims, "session_id"),
            task_id=_string_claim(claims, "task_id"),
            roles=_string_list_claim(claims, "roles"),
            permissions=_string_list_claim(claims, "permissions"),
            allowed_tools=_string_list_claim(claims, "allowed_tools"),
            allowed_actions=_string_list_claim(claims, "allowed_actions"),
        )


def _string_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise GatewayError("CAPABILITY_TOKEN_INVALID")
    return value


def _string_list_claim(claims: dict[str, Any], name: str) -> tuple[str, ...]:
    value = claims.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GatewayError("CAPABILITY_TOKEN_INVALID")
    return tuple(value)
