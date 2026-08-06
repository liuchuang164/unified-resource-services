from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_header_trusted_context_overrides_legacy_body(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post(
        "/external/dispatch",
        headers={
            "x-tenant-id": "tenant_A",
            "x-biz-domain": "LEGAL",
            "x-user-id": "user_001",
            "x-caller-id": "svc_001",
            "x-caller-type": "BUSINESS_SERVICE",
            "x-trace-id": "trusted_trace",
            "x-roles": "LAWYER",
        },
        json=dispatch_payload(trace_id="body_trace"),
    )
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["trace_id"] == "trusted_trace"


def test_header_tenant_conflict_rejected(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post(
        "/external/dispatch",
        headers={
            "x-tenant-id": "tenant_B",
            "x-biz-domain": "LEGAL",
            "x-user-id": "user_001",
        },
        json=dispatch_payload(),
    )
    assert response.json()["error"]["code"] == "TENANT_SCOPE_MISMATCH"


def test_context_spoofing_inside_payload_rejected(
    client: TestClient, dispatch_payload: Callable[..., dict[str, Any]]
) -> None:
    response = client.post(
        "/external/dispatch",
        headers={
            "x-tenant-id": "tenant_A",
            "x-biz-domain": "LEGAL",
            "x-user-id": "user_001",
            "x-roles": "LAWYER",
        },
        json=dispatch_payload(payload={"query": "x", "biz_domain": "FINANCE"}),
    )
    assert response.json()["error"]["code"] == "BIZ_DOMAIN_SCOPE_MISMATCH"
