from collections.abc import Mapping
from datetime import datetime
from typing import Any

import structlog

from file_media_stream_service.application.dto import RequestContext
from file_media_stream_service.domain.exceptions import PermissionDenied, Unauthenticated

logger = structlog.get_logger(__name__)


class ExternalSecurityBoundary:
    """Fail-closed boundary until a production IAM adapter is injected."""

    async def verify(self, context: RequestContext) -> None:
        if not context.caller_id or not context.tenant_id or not context.biz_domain:
            raise Unauthenticated("Caller identity is incomplete")

    async def verify_capability(self, context: RequestContext, operation: str) -> None:
        if context.caller_type == "agent":
            raise Unauthenticated("Production capability verification is not configured")

    async def authorize(
        self, context: RequestContext, operation: str, resource_scope: str | None
    ) -> None:
        raise PermissionDenied("Production authorization is not configured")


class UnavailableMediaServer:
    async def create_session(
        self, protocol: str, direction: str, lease_expires_at: datetime
    ) -> str:
        raise RuntimeError("Media server integration is outside Phase 1")

    async def close_session(self, endpoint_reference: str) -> None:
        raise RuntimeError("Media server integration is outside Phase 1")


class UnavailableProcessor:
    async def submit(
        self, processor_type: str, input_resource_id: str, options: Mapping[str, Any]
    ) -> None:
        raise RuntimeError("Processor integration is outside Phase 1")


class StructuredEventBus:
    async def publish(self, event_name: str, payload: Mapping[str, Any]) -> None:
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key in {"resource_id", "session_id", "job_id"}
        }
        logger.info("domain_event", event_name=event_name, **safe_payload)
