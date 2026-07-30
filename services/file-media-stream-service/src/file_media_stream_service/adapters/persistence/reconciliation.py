from collections.abc import Mapping
from typing import Any


class InMemoryReconciliationStore:
    """Models durable pending recovery records for later persistent adapter replacement."""

    def __init__(self) -> None:
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}

    async def record(self, key: str, kind: str, payload: Mapping[str, Any]) -> None:
        self.pending[key] = (kind, dict(payload))

    async def resolve(self, key: str, tenant_id: str, biz_domain: str) -> None:
        del tenant_id, biz_domain
        self.pending.pop(key, None)
