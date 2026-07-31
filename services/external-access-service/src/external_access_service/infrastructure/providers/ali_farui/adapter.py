import hashlib
import hmac
import json
from typing import Any

import httpx

from external_access_service.application.ports.protocols import ExternalProviderPort
from external_access_service.domain.errors import (
    OperationNotAllowed,
    ProviderAuthFailed,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from external_access_service.domain.models import (
    ExternalDispatchRequest,
    ProviderCode,
    ProviderCredential,
    ProviderResult,
    Usage,
)
from external_access_service.infrastructure.observability.redaction import redact

FARUI_OPERATION_PATHS = {
    "ALI_FARUI_LEGAL_CONSULT": "/legal/consult",
    "ALI_FARUI_LAW_SEARCH": "/legal/law-search",
    "ALI_FARUI_CASE_SEARCH": "/legal/case-search",
    "ALI_FARUI_LEGAL_RESEARCH_FULL": "/legal/research-full",
}


class AliFaruiAdapter(ExternalProviderPort):
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=self.base_url)

    def provider_code(self) -> ProviderCode:
        return ProviderCode.ALI_FARUI

    def supports(self, operation: str) -> bool:
        return operation in FARUI_OPERATION_PATHS

    async def execute(
        self, request: ExternalDispatchRequest, credential: ProviderCredential
    ) -> ProviderResult:
        path = FARUI_OPERATION_PATHS.get(request.operation)
        if path is None:
            raise OperationNotAllowed("ALI_FARUI operation mapping is not registered")
        payload = self._build_payload(request)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = self._headers(credential, body, request.trace_id)
        try:
            response = await self.client.post(
                path,
                content=body,
                headers=headers,
                timeout=httpx.Timeout(request.policy.timeout_ms / 1000),
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("ALI_FARUI request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable("ALI_FARUI transport unavailable") from exc

        provider_request_id = response.headers.get("x-request-id") or response.headers.get(
            "x-farui-request-id"
        )
        if response.status_code in {401, 403}:
            raise ProviderAuthFailed(
                "ALI_FARUI authentication failed",
                {"http_status": response.status_code, "provider": "ALI_FARUI"},
            )
        if response.status_code == 429:
            raise ProviderRateLimited(
                "ALI_FARUI rate limited the request",
                {
                    "http_status": 429,
                    "retry_after": response.headers.get("retry-after"),
                    "provider_request_id": provider_request_id,
                },
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                "ALI_FARUI service is unavailable",
                {"http_status": response.status_code, "provider_request_id": provider_request_id},
            )
        if response.status_code >= 400:
            raise ProviderBadResponse(
                "ALI_FARUI returned an invalid request error",
                {"http_status": response.status_code, "provider_request_id": provider_request_id},
            )
        try:
            raw = response.json()
        except ValueError as exc:
            raise ProviderBadResponse("ALI_FARUI response is not JSON") from exc
        if not isinstance(raw, dict) or not raw:
            raise ProviderBadResponse("ALI_FARUI response is empty or malformed")
        return ProviderResult(
            data=self._normalize_response(raw),
            usage=Usage(
                request_count=1,
                input_units=len(str(request.payload.get("query", ""))),
                output_units=len(str(raw)),
                estimated_cost=0,
            ),
            provider_request_id=provider_request_id,
        )

    async def health_check(self) -> dict[str, str]:
        return {"provider": ProviderCode.ALI_FARUI.value, "status": "configured"}

    @staticmethod
    def _build_payload(request: ExternalDispatchRequest) -> dict[str, Any]:
        query = request.payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProviderBadResponse("Provider payload requires a non-empty query")
        mapped: dict[str, Any] = {
            "requestId": request.request_id,
            "traceId": request.trace_id,
            "operation": request.operation,
            "query": query,
        }
        if "limit" in request.payload:
            mapped["limit"] = request.payload["limit"]
        return mapped

    @staticmethod
    def _headers(
        credential: ProviderCredential, body: bytes, trace_id: str
    ) -> dict[str, str]:
        digest = hmac.new(credential.api_secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "content-type": "application/json",
            "x-api-key": credential.api_key,
            "x-signature": digest,
            "x-trace-id": trace_id,
        }
        if credential.token:
            headers["authorization"] = f"Bearer {credential.token}"
        return headers

    @staticmethod
    def _normalize_response(raw: dict[str, Any]) -> dict[str, Any]:
        safe = redact(raw)
        data = safe.get("data", safe)
        if not isinstance(data, dict):
            raise ProviderBadResponse("ALI_FARUI data field is malformed")
        return {
            "summary": data.get("summary") or data.get("answer") or data.get("result"),
            "items": data.get("items", []),
            "provider_status": safe.get("status") or safe.get("code"),
        }
