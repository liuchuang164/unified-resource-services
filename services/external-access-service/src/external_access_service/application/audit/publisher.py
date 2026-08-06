import structlog

from external_access_service.application.ports.protocols import AuditSinkPort
from external_access_service.infrastructure.observability.redaction import redact

logger = structlog.get_logger(__name__)


class AuditEventPublisher:
    async def publish(self, event: dict[str, object]) -> None:
        raise NotImplementedError


class SyncAuditEventPublisher(AuditEventPublisher):
    def __init__(self, sink: AuditSinkPort) -> None:
        self.sink = sink

    async def publish(self, event: dict[str, object]) -> None:
        try:
            await self.sink.write(redact(event))
        except Exception:
            logger.error(
                "audit_publish_failed",
                request_id=event.get("request_id"),
                trace_id=event.get("trace_id"),
                tenant_id=event.get("tenant_id"),
                biz_domain=event.get("biz_domain"),
                operation=event.get("operation"),
            )
