from typing import Any

from pydantic import BaseModel, ConfigDict

from external_access_service.domain.errors import OperationNotFound
from external_access_service.domain.models import ProviderCode


class OperationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    provider_code: ProviderCode
    capability: str
    allowed_biz_domains: tuple[str, ...]
    enabled: bool = True
    payload_schema: dict[str, Any]


QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 4096},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
}

OPERATIONS: tuple[OperationDefinition, ...] = (
    OperationDefinition(
        operation="ALI_FARUI_LEGAL_CONSULT",
        provider_code=ProviderCode.ALI_FARUI,
        capability="LEGAL_CONSULT",
        allowed_biz_domains=("LEGAL",),
        payload_schema=QUERY_SCHEMA,
    ),
    OperationDefinition(
        operation="ALI_FARUI_LAW_SEARCH",
        provider_code=ProviderCode.ALI_FARUI,
        capability="LEGAL_RESEARCH",
        allowed_biz_domains=("LEGAL",),
        payload_schema=QUERY_SCHEMA,
    ),
    OperationDefinition(
        operation="ALI_FARUI_CASE_SEARCH",
        provider_code=ProviderCode.ALI_FARUI,
        capability="LEGAL_RESEARCH",
        allowed_biz_domains=("LEGAL",),
        payload_schema=QUERY_SCHEMA,
    ),
    OperationDefinition(
        operation="ALI_FARUI_LEGAL_RESEARCH_FULL",
        provider_code=ProviderCode.ALI_FARUI,
        capability="LEGAL_RESEARCH",
        allowed_biz_domains=("LEGAL",),
        payload_schema=QUERY_SCHEMA,
    ),
)


class OperationRegistry:
    def __init__(self, operations: tuple[OperationDefinition, ...] = OPERATIONS) -> None:
        self._operations = {item.operation: item for item in operations}

    def list(self, tenant_id: str, biz_domain: str) -> list[OperationDefinition]:
        return [
            item
            for item in self._operations.values()
            if item.enabled and biz_domain in item.allowed_biz_domains and tenant_id
        ]

    def get(self, operation: str) -> OperationDefinition:
        try:
            return self._operations[operation]
        except KeyError as exc:
            raise OperationNotFound("Operation is not registered") from exc
