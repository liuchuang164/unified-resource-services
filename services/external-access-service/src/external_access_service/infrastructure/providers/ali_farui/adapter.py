import hashlib
import hmac
import json
from typing import Any
from urllib.parse import quote, urlencode, urlparse

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
    "ALI_FARUI_LEGAL_CONSULT": "/farui/legalAdvice/consult",
    "ALI_FARUI_LAW_SEARCH": "/farui/search/law/query",
    "ALI_FARUI_CASE_SEARCH": "/farui/search/case/fulltext",
    "ALI_FARUI_LEGAL_RESEARCH_FULL": "/farui/search/case/fulltext",
}

FARUI_OPERATION_ACTIONS = {
    "ALI_FARUI_LEGAL_CONSULT": "RunLegalAdviceConsultation",
    "ALI_FARUI_LAW_SEARCH": "RunSearchLawQuery",
    "ALI_FARUI_CASE_SEARCH": "RunSearchCaseFullText",
    "ALI_FARUI_LEGAL_RESEARCH_FULL": "RunSearchCaseFullText",
}
FARUI_APP_ID = "farui"
FARUI_API_VERSION = "2024-06-28"


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
        payload = self._build_payload(request, credential)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        url = self._url(path, credential)
        headers = self._headers(credential, body, request.trace_id, request.operation, url)
        try:
            response = await self.client.post(
                url,
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
            retry_after = response.headers.get("retry-after")
            raise ProviderRateLimited(
                "ALI_FARUI rate limited the request",
                {
                    "http_status": 429,
                    "retry_after": retry_after,
                    "retry_after_seconds": retry_after,
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
        raw = self._parse_response(response)
        if not isinstance(raw, dict) or not raw:
            raise ProviderBadResponse("ALI_FARUI response is empty or malformed")
        return ProviderResult(
            data=self._normalize_response(raw, request.operation),
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
    def _build_payload(
        request: ExternalDispatchRequest, credential: ProviderCredential
    ) -> dict[str, Any]:
        query = request.payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProviderBadResponse("Provider payload requires a non-empty query")
        if credential.auth_mode == "workspace_api_key":
            return AliFaruiAdapter._build_workspace_api_key_payload(request, query, credential)
        workspace_id = credential.workspace_id
        if not workspace_id:
            raise ProviderAuthFailed("ALI_FARUI workspace is missing")
        mapped: dict[str, Any] = {"appId": FARUI_APP_ID, "workspaceId": workspace_id}
        if request.operation == "ALI_FARUI_LEGAL_CONSULT":
            mapped["stream"] = True
            mapped["thread"] = {"messages": [{"role": "user", "content": query}]}
            return mapped
        mapped["query"] = query
        mapped["pageParam"] = {
            "pageNumber": int(request.payload.get("page_number", 1)),
            "pageSize": int(request.payload.get("limit", request.payload.get("page_size", 5))),
        }
        if request.operation in {"ALI_FARUI_CASE_SEARCH", "ALI_FARUI_LEGAL_RESEARCH_FULL"}:
            mapped["thread"] = {"messages": [{"role": "user", "content": query}]}
        if "limit" in request.payload:
            mapped["limit"] = request.payload["limit"]
        return mapped

    @staticmethod
    def _build_workspace_api_key_payload(
        request: ExternalDispatchRequest, query: str, credential: ProviderCredential
    ) -> dict[str, Any]:
        instruction = {
            "ALI_FARUI_LEGAL_CONSULT": "请以法律咨询助手身份回答, 给出结论、依据和风险提示。",
            "ALI_FARUI_LAW_SEARCH": "请检索并列出相关法律法规、条文标题、适用要点。",
            "ALI_FARUI_CASE_SEARCH": "请检索并列出相关类案、裁判要旨和风险要点。",
            "ALI_FARUI_LEGAL_RESEARCH_FULL": "请综合检索法规与类案, 输出法律研究摘要、依据和风险。",
        }[request.operation]
        prompt = f"{instruction}\n\n问题: {query}"
        if credential.endpoint and "compatible-mode" not in credential.endpoint:
            return {
                "input": {"prompt": prompt},
                "parameters": {},
                "debug": {
                    "request_id": request.request_id,
                    "trace_id": request.trace_id,
                    "operation": request.operation,
                },
            }
        return {
            "model": credential.model or "farui",
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": query},
            ],
            "stream": False,
            "metadata": {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "operation": request.operation,
            },
        }

    def _url(self, path: str, credential: ProviderCredential) -> str:
        if credential.auth_mode == "workspace_api_key":
            endpoint = (credential.endpoint or self.base_url).rstrip("/")
            if "compatible-mode" in endpoint:
                return f"{endpoint}/chat/completions"
            return f"{endpoint}/apps/{credential.model or 'farui'}/completion"
        workspace_id = credential.workspace_id
        if not workspace_id:
            raise ProviderAuthFailed("ALI_FARUI workspace is missing")
        return f"{self.base_url}/{workspace_id}{path}"

    @staticmethod
    def _headers(
        credential: ProviderCredential,
        body: bytes,
        trace_id: str,
        operation: str,
        url: str,
    ) -> dict[str, str]:
        if credential.auth_mode == "workspace_api_key":
            return {
                "content-type": "application/json",
                "authorization": f"Bearer {credential.api_key}",
                "x-trace-id": trace_id,
            }
        headers = {
            "host": urlparse(url).netloc,
            "content-type": "application/json",
            "x-acs-action": FARUI_OPERATION_ACTIONS[operation],
            "x-acs-version": FARUI_API_VERSION,
            "x-acs-date": httpx.Headers().get("date", ""),
            "x-trace-id": trace_id,
        }
        if not headers["x-acs-date"]:
            from datetime import UTC, datetime

            headers["x-acs-date"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.loads(body.decode("utf-8"))
        headers["authorization"] = AliFaruiAdapter._acs3_authorization(
            url, "POST", headers, payload, credential.api_key, credential.api_secret
        )
        return headers

    @staticmethod
    def _acs3_authorization(
        url: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any],
        access_key_id: str,
        access_key_secret: str,
    ) -> str:
        parsed = urlparse(url)
        canonical_uri = parsed.path or "/"
        query_params: dict[str, str] = {}
        if parsed.query:
            query_params = dict(part.split("=", 1) for part in parsed.query.split("&"))
        canonical_query_string = urlencode(
            {
                AliFaruiAdapter._rfc3986_encode(k): AliFaruiAdapter._rfc3986_encode(v)
                for k, v in sorted(query_params.items())
            }
        )
        headers_lower = {key.lower(): value.strip() for key, value in headers.items()}
        signed_header_names = sorted(
            key
            for key in headers_lower
            if key.startswith("x-acs-") or key in {"host", "content-type"}
        )
        canonical_headers = "".join(
            f"{key}:{headers_lower[key]}\n" for key in signed_header_names
        )
        signed_headers = ";".join(signed_header_names)
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                canonical_query_string,
                canonical_headers,
                signed_headers,
                hashed_payload,
            ]
        )
        algorithm = "ACS3-HMAC-SHA256"
        hashed_canonical_request = hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()
        string_to_sign = f"{algorithm}\n{hashed_canonical_request}"
        signature = hmac.new(
            access_key_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return (
            f"{algorithm} Credential={access_key_id},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )

    @staticmethod
    def _rfc3986_encode(value: str) -> str:
        return quote(str(value), safe="-._~")

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return AliFaruiAdapter._parse_sse(response.text)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise ProviderBadResponse("ALI_FARUI response is not JSON") from exc
        if not isinstance(parsed, dict):
            raise ProviderBadResponse("ALI_FARUI response is not a JSON object")
        return parsed

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        chunks: list[Any] = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunks.append(json.loads(data))
            except ValueError:
                chunks.append({"text": data})
        if not chunks:
            raise ProviderBadResponse("ALI_FARUI SSE response is empty")
        return {"data": {"chunks": chunks}}

    @staticmethod
    def _normalize_response(raw: dict[str, Any], operation: str) -> dict[str, Any]:
        safe = redact(raw)
        if "choices" in safe:
            return AliFaruiAdapter._normalize_chat_response(safe, operation)
        if "output" in safe:
            return AliFaruiAdapter._normalize_app_response(safe, operation)
        data = safe.get("data", safe)
        if not isinstance(data, dict):
            raise ProviderBadResponse("ALI_FARUI data field is malformed")
        if "lawResult" in data:
            items = [AliFaruiAdapter._safe_law_item(item) for item in data.get("lawResult", [])]
            return {
                "summary": f"法条检索返回 {data.get('totalCount', len(items))} 条结果",
                "items": items,
                "provider_status": safe.get("status") or safe.get("code"),
            }
        if "caseResult" in data:
            items = [AliFaruiAdapter._safe_case_item(item) for item in data.get("caseResult", [])]
            return {
                "summary": f"案例检索返回 {data.get('totalCount', len(items))} 条结果",
                "items": items,
                "provider_status": safe.get("status") or safe.get("code"),
            }
        if "chunks" in data:
            text = AliFaruiAdapter._extract_text(data["chunks"])
            return {"summary": text, "items": [], "provider_status": "OK"}
        return {
            "summary": data.get("summary") or data.get("answer") or data.get("result"),
            "items": data.get("items", []),
            "provider_status": safe.get("status") or safe.get("code"),
        }

    @staticmethod
    def _normalize_chat_response(raw: dict[str, Any], operation: str) -> dict[str, Any]:
        choices = raw.get("choices") if isinstance(raw.get("choices"), list) else []
        content = ""
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                else:
                    content = str(first.get("text") or "")
        return {
            "summary": content,
            "items": [],
            "provider_status": raw.get("object") or raw.get("id") or operation,
        }

    @staticmethod
    def _normalize_app_response(raw: dict[str, Any], operation: str) -> dict[str, Any]:
        output = raw.get("output")
        content = ""
        if isinstance(output, dict):
            content = str(
                output.get("text")
                or output.get("answer")
                or output.get("content")
                or output.get("message")
                or ""
            )
        return {
            "summary": content,
            "items": [],
            "provider_status": raw.get("code") or raw.get("request_id") or operation,
        }

    @staticmethod
    def _safe_law_item(item: Any) -> dict[str, Any]:
        law = item.get("lawDomain", {}) if isinstance(item, dict) else {}
        return {
            "title": law.get("lawTitle") or law.get("lawName"),
            "law_name": law.get("lawName"),
            "law_item_id": law.get("lawItemId"),
            "timeliness": law.get("timeliness"),
            "similarity": item.get("similarity") if isinstance(item, dict) else None,
        }

    @staticmethod
    def _safe_case_item(item: Any) -> dict[str, Any]:
        case = item.get("caseDomain", {}) if isinstance(item, dict) else {}
        trial_court = case.get("trialCourt")
        if isinstance(trial_court, dict):
            trial_court = trial_court.get("name")
        return {
            "title": case.get("caseTitle"),
            "case_no": case.get("caseNo"),
            "case_cause": case.get("caseCause"),
            "trial_court": trial_court,
            "trial_date": case.get("trialDate"),
            "similarity": item.get("similarity") if isinstance(item, dict) else None,
        }

    @staticmethod
    def _extract_text(chunks: list[Any]) -> str:
        parts: list[str] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                for key in ("answer", "content", "text", "result"):
                    value = chunk.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
                choices = chunk.get("choices")
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                        parts.append(delta["content"])
            elif isinstance(chunk, str):
                parts.append(chunk)
        return "".join(parts).strip()
