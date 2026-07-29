from typing import Any

import pytest
from httpx import AsyncClient

from data_control_service.api.dependencies import get_data_control_service
from data_control_service.ports.idempotency_repository import IdempotencyRepository


class FailOnceMarkSucceededRepository:
    def __init__(self, wrapped: IdempotencyRepository) -> None:
        self._wrapped = wrapped
        self.failed_once = False

    async def claim(self, *args: Any, **kwargs: Any) -> Any:
        return await self._wrapped.claim(*args, **kwargs)

    async def mark_succeeded(self, *args: Any, **kwargs: Any) -> None:
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("test-only mark_succeeded failure")
        await self._wrapped.mark_succeeded(*args, **kwargs)

    async def mark_failed(self, *args: Any, **kwargs: Any) -> None:
        await self._wrapped.mark_failed(*args, **kwargs)

    async def mark_recovery_required(self, *args: Any, **kwargs: Any) -> None:
        await self._wrapped.mark_recovery_required(*args, **kwargs)

    async def mark_recovery_succeeded(self, *args: Any, **kwargs: Any) -> None:
        await self._wrapped.mark_recovery_succeeded(*args, **kwargs)

    async def mark_recovery_failed(self, *args: Any, **kwargs: Any) -> None:
        await self._wrapped.mark_recovery_failed(*args, **kwargs)

    async def list_recovery_required(self, *args: Any, **kwargs: Any) -> Any:
        return await self._wrapped.list_recovery_required(*args, **kwargs)

    async def health(self) -> dict[str, str]:
        return await self._wrapped.health()


def recovery_request() -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "request_id": "req_RECOVERY_TEST",
        "trace_id": "trace_RECOVERY_TEST",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": "CREATE",
        "resource": {
            "target": "POSTGRESQL",
            "type": "DOCUMENT_RECORD",
            "name": "record",
            "resource_id": "doc_recovery",
        },
        "payload": {
            "data": {"id": "doc_recovery", "title": "recovery"},
            "query": {},
            "options": {},
        },
        "idempotency_key": "idem_RECOVERY_TEST",
        "transaction": {"mode": "LOCAL", "isolation": "READ_COMMITTED"},
        "timeout_ms": 5000,
        "metadata": {"caller_service": "test"},
    }


@pytest.mark.consistency
async def test_mark_succeeded_failure_enters_recovery_without_duplicate_write(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "CONTROL_DATABASE_URL",
        "CONTROL_DATABASE_MIGRATION_URL",
        "POSTGRESQL_ADAPTER_DATABASE_URL",
        "TARGET_DATABASE_MIGRATION_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("POSTGRESQL_ADAPTER_ENABLED", "false")
    get_data_control_service.cache_clear()
    service = get_data_control_service()
    wrapped = FailOnceMarkSucceededRepository(service._idempotency_service._repository)
    monkeypatch.setattr(service._idempotency_service, "_repository", wrapped)

    first = await client.post("/data/dispatch", json=recovery_request())
    second = await client.post("/data/dispatch", json=recovery_request())

    assert first.status_code == 409
    assert first.json()["code"] == "IDEMPOTENCY_RECOVERY_REQUIRED"
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_RECOVERY_REQUIRED"
    assert service._idempotency_service.adapter_execution_count == 1
