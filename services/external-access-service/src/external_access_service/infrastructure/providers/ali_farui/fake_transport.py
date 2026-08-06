import json
from collections.abc import Callable

import httpx


def farui_mock_transport(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.MockTransport:
    def default(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        action = request.headers.get("x-acs-action", "RunSearchCaseFullText")
        query = payload.get("query") or payload.get("messages", [{}])[-1].get("content") or ""
        if action == "RunSearchLawQuery":
            data = {
                "lawResult": [
                    {
                        "lawDomain": {
                            "lawName": "中华人民共和国民法典",
                            "lawTitle": "合同编通则",
                            "lawItemId": "mock-law-1",
                        },
                        "similarity": 0.9,
                    }
                ],
                "totalCount": 1,
            }
        elif action == "RunLegalAdviceConsultation":
            data = {"answer": f"mock consult result for {query[:64]}"}
        else:
            data = {
                "caseResult": [
                    {
                        "caseDomain": {
                            "caseTitle": "mock case",
                            "caseNo": "mock-no",
                            "caseCause": "民间借贷纠纷",
                        },
                        "similarity": 0.8,
                    }
                ],
                "totalCount": 1,
            }
        return httpx.Response(
            200,
            headers={"x-farui-request-id": "farui_mock_1"},
            json={"status": "OK", "data": data},
        )

    return httpx.MockTransport(handler or default)
