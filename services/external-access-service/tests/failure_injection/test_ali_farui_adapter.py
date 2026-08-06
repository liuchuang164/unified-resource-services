import json
from collections.abc import Callable

import httpx
import pytest
from conftest import container_with_transport

from external_access_service.domain.models import ExternalDispatchRequest


@pytest.mark.asyncio
async def test_farui_request_mapping_and_signature(
    dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["authorization"]
        seen["action"] = request.headers["x-acs-action"]
        seen["version"] = request.headers["x-acs-version"]
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            headers={"x-request-id": "rid"},
            json={"data": {"caseResult": [], "totalCount": 0}},
        )

    container = container_with_transport(handler)
    response = await container.entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert seen["path"] == "/test-workspace/farui/search/case/fulltext"
    assert seen["authorization"].startswith("ACS3-HMAC-SHA256 Credential=test-api-key")
    assert "Signature=" in seen["authorization"]
    assert seen["action"] == "RunSearchCaseFullText"
    assert seen["version"] == "2024-06-28"
    assert json.loads(seen["body"])["query"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_UNAVAILABLE"),
    ],
)
async def test_farui_http_error_mapping(
    dispatch_request: Callable[..., ExternalDispatchRequest], status_code: int, expected: str
) -> None:
    container = container_with_transport(
        lambda request: httpx.Response(status_code, json={"error": "x"})
    )
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == expected


@pytest.mark.asyncio
async def test_farui_non_json_response(
    dispatch_request: Callable[..., ExternalDispatchRequest]
) -> None:
    container = container_with_transport(lambda request: httpx.Response(200, content=b"not-json"))
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == "PROVIDER_BAD_RESPONSE"


@pytest.mark.asyncio
async def test_farui_empty_response(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    container = container_with_transport(lambda request: httpx.Response(200, json={}))
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == "PROVIDER_BAD_RESPONSE"


@pytest.mark.asyncio
async def test_farui_retry_success(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(500, json={"error": "try again"})
        return httpx.Response(200, json={"data": {"answer": "ok"}})

    container = container_with_transport(handler)
    response = await container.entry.dispatch(dispatch_request())
    assert response.status.value == "SUCCEEDED"
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_farui_retry_exhausted(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    container = container_with_transport(lambda request: httpx.Response(500, json={"error": "x"}))
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == "PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_farui_connection_failure(
    dispatch_request: Callable[..., ExternalDispatchRequest],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    container = container_with_transport(handler)
    response = await container.entry.dispatch(dispatch_request())
    assert response.error is not None
    assert response.error.code == "PROVIDER_UNAVAILABLE"
