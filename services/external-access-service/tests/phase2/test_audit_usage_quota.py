from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from external_access_service.application.governance import QuotaRule
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCode


def test_audit_query_is_persistent_and_scoped(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    client.post("/external/dispatch", json=dispatch_payload(request_id="req_audit"))
    audit = client.get(
        "/external/audit",
        params={"tenant_id": "tenant_A", "biz_domain": "LEGAL", "request_id": "req_audit"},
    ).json()["audit"]
    assert len(audit) == 1
    assert audit[0]["request_id"] == "req_audit"
    assert "payload" not in audit[0]


def test_failed_call_is_audited(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    client.post("/external/dispatch", json=dispatch_payload(operation="UNKNOWN"))
    audit = client.get(
        "/external/audit",
        params={"tenant_id": "tenant_A", "biz_domain": "LEGAL", "status": "FAILED"},
    ).json()["audit"]
    assert audit[-1]["error_code"] == "OPERATION_NOT_FOUND"


def test_usage_query_groups_by_operation(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    client.post("/external/dispatch", json=dispatch_payload(request_id="req_usage"))
    usage = client.get(
        "/external/usage",
        params={"tenant_id": "tenant_A", "biz_domain": "LEGAL"},
    ).json()["usage"]
    assert usage[0]["operation"] == "ALI_FARUI_LEGAL_RESEARCH_FULL"
    assert usage[0]["request_count"] >= 1
    assert usage[0]["estimated_cost"] > 0


def test_usage_isolation_blocks_cross_tenant_query(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    client.post("/external/dispatch", json=dispatch_payload(request_id="req_usage_iso"))
    usage = client.get(
        "/external/usage",
        headers={"x-tenant-id": "tenant_A", "x-biz-domain": "LEGAL", "x-user-id": "user_001"},
        params={"tenant_id": "tenant_B", "biz_domain": "LEGAL"},
    ).json()
    assert usage["error"]["code"] == "TENANT_SCOPE_MISMATCH"


@pytest.mark.asyncio
async def test_quota_exceeded(
    container, dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    container.quota.rules = (
        QuotaRule(
            tenant_id="tenant_A",
            biz_domain="LEGAL",
            operation="ALI_FARUI_LEGAL_RESEARCH_FULL",
            provider=ProviderCode.ALI_FARUI,
            daily_limit=1,
        ),
    )
    first = await container.entry.dispatch(dispatch_request(request_id="req_quota_1"))
    second = await container.entry.dispatch(dispatch_request(request_id="req_quota_2"))
    assert first.status.value == "SUCCEEDED"
    assert second.error is not None
    assert second.error.code == "QUOTA_EXCEEDED"
