import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from external_access_service.domain.errors import (
    CapabilityExpired,
    CapabilityInvalid,
    CapabilityScopeDenied,
)


class CapabilityClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    biz_domain: str = Field(min_length=1)
    allowed_operations: tuple[str, ...]
    expires_at: datetime
    signature: str


class CapabilityVerifier:
    def __init__(self, secret: str, issuer: str = "hermes") -> None:
        if not secret:
            raise ValueError("Capability verifier secret is required")
        self.secret = secret
        self.issuer = issuer

    def verify(
        self,
        token: str,
        *,
        tenant_id: str,
        biz_domain: str,
        operation: str,
    ) -> CapabilityClaims:
        raw = self._parse_raw(token)
        claims = self._parse(raw)
        if claims.issuer != self.issuer:
            raise CapabilityInvalid("Capability issuer is not trusted")
        if not hmac.compare_digest(claims.signature, self._signature_from_raw(raw)):
            raise CapabilityInvalid("Capability signature is invalid")
        if claims.expires_at <= datetime.now(UTC):
            raise CapabilityExpired("Capability token is expired")
        if claims.tenant_id != tenant_id:
            raise CapabilityScopeDenied("Capability tenant scope denied")
        if claims.biz_domain != biz_domain:
            raise CapabilityScopeDenied("Capability business-domain scope denied")
        if operation not in claims.allowed_operations:
            raise CapabilityScopeDenied("Capability operation scope denied")
        return claims

    def issue_for_test(self, claims: dict[str, Any]) -> str:
        unsigned = dict(claims)
        unsigned.pop("signature", None)
        unsigned["signature"] = self._signature_from_dict(unsigned)
        return json.dumps(unsigned, separators=(",", ":"), sort_keys=True)

    def _parse_raw(self, token: str) -> dict[str, Any]:
        try:
            raw = json.loads(token)
        except ValueError as exc:
            raise CapabilityInvalid("Capability token is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise CapabilityInvalid("Capability token must be a JSON object")
        return raw

    def _parse(self, raw: dict[str, Any]) -> CapabilityClaims:
        try:
            return CapabilityClaims.model_validate(raw)
        except ValueError as exc:
            raise CapabilityInvalid("Capability token claims are invalid") from exc

    def _signature_from_raw(self, raw: dict[str, Any]) -> str:
        unsigned = dict(raw)
        unsigned.pop("signature", None)
        return self._signature_from_dict(unsigned)

    def _signature(self, claims: CapabilityClaims) -> str:
        raw = claims.model_dump(mode="json", exclude={"signature"})
        return self._signature_from_dict(raw)

    def _signature_from_dict(self, raw: dict[str, Any]) -> str:
        canonical = json.dumps(raw, separators=(",", ":"), sort_keys=True).encode()
        return hmac.new(self.secret.encode(), canonical, hashlib.sha256).hexdigest()
