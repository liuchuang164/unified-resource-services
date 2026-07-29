from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.application.audit_service import stable_digest
from data_control_service.contracts.enums import WRITE_OPERATIONS
from data_control_service.contracts.errors import ERROR_CATALOG
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.models import AdapterResult, ExecutionContext, RouteDecision
from data_control_service.infrastructure.persistence.models.access_audit import (
    AccessAuditLogModel,
)
from data_control_service.infrastructure.persistence.models.change_audit import (
    ChangeAuditLogModel,
)
from data_control_service.ports.audit_repository import AuditRepository


class SQLAlchemyAuditRepository(AuditRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_access(
        self,
        request: DataRequest,
        context: ExecutionContext,
        *,
        status: str,
        code: str,
        latency_ms: int,
        route: RouteDecision | None = None,
    ) -> None:
        spec = ERROR_CATALOG.get(code)
        target = route.target.value if route else request.resource.target.value
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    AccessAuditLogModel(
                        id=f"audit_{uuid4().hex}",
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        tenant_id=context.tenant_id,
                        biz_domain=context.biz_domain,
                        actor_id=context.subject_id,
                        actor_type=context.subject_type,
                        source=context.source,
                        operation=request.operation.value,
                        target=target,
                        logical_resource_type=request.resource.type,
                        logical_resource_name=request.resource.name,
                        resource_id=request.resource.resource_id,
                        policy_decision="ALLOW" if status in {"SUCCEEDED", "REPLAYED"} else "DENY",
                        policy_id=None,
                        result_status=status,
                        http_status=spec.http_status if spec else 200,
                        error_code=None if code == "OK" else code,
                        retryable=spec.retryable if spec else False,
                        latency_ms=latency_ms,
                        metadata_digest=stable_digest(request.metadata),
                        created_at=now,
                    )
                )

    async def record_change(
        self,
        request: DataRequest,
        context: ExecutionContext,
        result: AdapterResult,
        *,
        status: str,
        code: str,
        route: RouteDecision,
    ) -> None:
        if request.operation not in WRITE_OPERATIONS or status != "SUCCEEDED":
            return
        now = datetime.now(UTC)
        changed_fields = (
            sorted(request.payload.data) if isinstance(request.payload.data, dict) else []
        )
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    ChangeAuditLogModel(
                        id=f"change_{uuid4().hex}",
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        tenant_id=context.tenant_id,
                        biz_domain=context.biz_domain,
                        actor_id=context.subject_id,
                        target=route.target.value,
                        logical_resource_type=request.resource.type,
                        logical_resource_name=request.resource.name,
                        resource_id=request.resource.resource_id
                        or str((result.data or {}).get("resource_id", "")),
                        operation=request.operation.value,
                        before_digest=None,
                        after_digest=stable_digest(result.data),
                        changed_fields={"fields": changed_fields},
                        result_status=status,
                        error_code=None if code == "OK" else code,
                        created_at=now,
                    )
                )

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            await session.execute(select(AccessAuditLogModel.id).limit(1))
        return {"status": "ok", "backend": "postgresql"}
