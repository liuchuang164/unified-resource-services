from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    http_status: int
    message: str
    retryable: bool = False


ERROR_CATALOG = {
    "TOOL_NOT_FOUND": ErrorSpec(404, "tool was not found"),
    "TOOL_ACTION_NOT_SUPPORTED": ErrorSpec(422, "tool action is not supported"),
    "TOOL_PARAMS_INVALID": ErrorSpec(400, "tool parameters are invalid"),
    "CAPABILITY_TOKEN_REQUIRED": ErrorSpec(401, "capability token is required"),
    "CAPABILITY_TOKEN_INVALID": ErrorSpec(401, "capability token is invalid"),
    "CAPABILITY_SCOPE_DENIED": ErrorSpec(403, "capability scope is denied"),
    "TOOL_SCOPE_MISMATCH": ErrorSpec(403, "tool request scope does not match capability"),
    "DATA_CONTROL_UNAVAILABLE": ErrorSpec(503, "data control service is unavailable", True),
    "DATA_CONTROL_TIMEOUT": ErrorSpec(504, "data control service timed out", True),
    "DATA_CONTROL_RESPONSE_INVALID": ErrorSpec(502, "data control response is invalid", True),
    "TOOL_EXECUTION_FAILED": ErrorSpec(500, "tool execution failed", True),
}


class GatewayError(Exception):
    def __init__(
        self,
        code: str,
        *,
        details: list[dict[str, object]] | None = None,
    ) -> None:
        self.code = code
        self.spec = ERROR_CATALOG[code]
        self.details = details or []
        super().__init__(self.spec.message)
