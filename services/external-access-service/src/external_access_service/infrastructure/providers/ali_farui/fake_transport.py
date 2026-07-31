import json
from collections.abc import Callable

import httpx


def farui_mock_transport(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.MockTransport:
    def default(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"x-farui-request-id": "farui_mock_1"},
            json={
                "status": "OK",
                "data": {
                    "summary": f"mock result for {payload['operation']}",
                    "items": [{"title": "mock", "snippet": payload["query"][:64]}],
                },
            },
        )

    return httpx.MockTransport(handler or default)
