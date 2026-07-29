from uuid import uuid4

import pytest
from sqlalchemy import func, select

from data_control_service.application.audit_outbox_processor import AuditOutboxProcessor
from data_control_service.config.settings import Settings
from data_control_service.infrastructure.persistence.database import DatabaseManager
from data_control_service.infrastructure.persistence.models.access_audit import AccessAuditLogModel
from data_control_service.infrastructure.persistence.models.audit_outbox import AuditOutboxModel
from data_control_service.infrastructure.persistence.repositories.sqlalchemy_audit_outbox import (
    SQLAlchemyAuditOutboxRepository,
)
from data_control_service.ports.audit_outbox_repository import AuditEventType, AuditOutboxEvent
from tests.postgresql_helpers import require_postgresql_urls


@pytest.mark.postgresql
@pytest.mark.consistency
async def test_audit_outbox_processor_materializes_access_audit() -> None:
    control_url, _ = require_postgresql_urls()
    manager = DatabaseManager(control_url, Settings(app_env="test"), name="control-outbox")
    repository = SQLAlchemyAuditOutboxRepository(manager.session_factory)
    request_id = f"req_outbox_{uuid4().hex}"
    event_id = f"event_outbox_{uuid4().hex}"
    try:
        await repository.enqueue(
            AuditOutboxEvent(
                event_id=event_id,
                tenant_id="tenant_demo",
                biz_domain="demo",
                request_id=request_id,
                trace_id=f"trace_outbox_{uuid4().hex}",
                actor_id="svc_demo",
                event_type=AuditEventType.ACCESS,
                target="POSTGRESQL",
                logical_resource_type="DOCUMENT_RECORD",
                logical_resource_name="record",
                resource_id="doc_outbox",
                operation="GET",
                audit_payload={
                    "request_id": request_id,
                    "trace_id": f"trace_outbox_payload_{uuid4().hex}",
                    "tenant_id": "tenant_demo",
                    "biz_domain": "demo",
                    "actor_id": "svc_demo",
                    "actor_type": "SERVICE",
                    "source": "BUSINESS_SERVICE",
                    "operation": "GET",
                    "target": "POSTGRESQL",
                    "logical_resource_type": "DOCUMENT_RECORD",
                    "logical_resource_name": "record",
                    "resource_id": "doc_outbox",
                    "policy_decision": "ALLOW",
                    "policy_id": None,
                    "result_status": "SUCCEEDED",
                    "http_status": 200,
                    "error_code": None,
                    "retryable": False,
                    "latency_ms": 1,
                    "metadata_digest": "0" * 64,
                },
                payload_digest="1" * 64,
                max_attempts=3,
            )
        )
        processor = AuditOutboxProcessor(
            outbox_repository=repository,
            audit_session_factory=manager.session_factory,
            worker_id=f"worker_{uuid4().hex}",
            batch_size=10,
            lock_timeout_seconds=30,
        )
        result = await processor.run_once()
        assert result == {"claimed": 1, "processed": 1, "failed": 0}
        async with manager.session() as session:
            audit_count = (
                await session.execute(
                    select(func.count())
                    .select_from(AccessAuditLogModel)
                    .where(AccessAuditLogModel.request_id == request_id)
                )
            ).scalar_one()
            outbox_status = (
                await session.execute(
                    select(AuditOutboxModel.status).where(AuditOutboxModel.event_id == event_id)
                )
            ).scalar_one()
        assert audit_count == 1
        assert outbox_status == "SUCCEEDED"
    finally:
        await manager.close()
