from external_access_service.infrastructure.observability.redaction import redact


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def write(self, event: dict[str, object]) -> None:
        self.events.append(redact(event))
