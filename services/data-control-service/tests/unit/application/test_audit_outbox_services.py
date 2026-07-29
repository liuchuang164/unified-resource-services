from datetime import datetime
from typing import Any

import pytest

from data_control_service.application.audit_outbox_processor import AuditOutboxProcessor
from data_control_service.application.audit_outbox_service import AuditOutboxService
from data_control_service.config.settings import Settings
from data_control_service.contracts.enums import DataTarget, Operation, TransactionMode
from data_control_service.contracts.request import DataRequest
from data_control_service.domain.models import AdapterResult, ExecutionContext, RouteDecision
from data_control_service.domain.policies import ResourceDefinition, ResourceMapping
from data_control_service.ports.audit_outbox_repository import (
    AuditEventType,
    AuditOutboxEvent,
    AuditOutboxRecord,
)


class FakeOutboxRepository:
    def __init__(self, claimed: list[AuditOutboxRecord] | None = None) -> None:
        self.enqueued: list[AuditOutboxEvent] = []
        self.claimed = claimed or []
        self.succeeded: list[tuple[str, str]] = []
        self.retried: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    async def enqueue(self, event: AuditOutboxEvent) -> None:
        self.enqueued.append(event)

    async def claim_batch(
        self, *, worker_id: str, limit: int, lock_timeout_seconds: int
    ) -> list[AuditOutboxRecord]:
        assert worker_id == "worker-1"
        assert limit == 10
        assert lock_timeout_seconds == 30
        return self.claimed

    async def mark_succeeded(self, record_id: str, worker_id: str) -> None:
        self.succeeded.append((record_id, worker_id))

    async def mark_retry(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
        next_retry_at: datetime,
    ) -> None:
        self.retried.append(
            {
                "record_id": record_id,
                "worker_id": worker_id,
                "error_code": error_code,
                "error_message_digest": error_message_digest,
                "next_retry_at": next_retry_at,
            }
        )

    async def mark_failed(
        self,
        record_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message_digest: str,
    ) -> None:
        self.failed.append(
            {
                "record_id": record_id,
                "worker_id": worker_id,
                "error_code": error_code,
                "error_message_digest": error_message_digest,
            }
        )

    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


class FakeSession:
    def __init__(self, added: list[object]) -> None:
        self._added = added

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self

    def add(self, model: object) -> None:
        self._added.append(model)


class FakeSessionFactory:
    def __init__(self) -> None:
        self.added: list[object] = []

    def __call__(self) -> FakeSession:
        return FakeSession(self.added)


class FailingAuditOutboxProcessor(AuditOutboxProcessor):
    async def _write_formal_audit(
        self, event_type: AuditEventType, payload: dict[str, object]
    ) -> None:
        raise RuntimeError(f"boom: {event_type}:{payload['request_id']}")


def make_request(operation: Operation = Operation.CREATE) -> DataRequest:
    return DataRequest.model_validate(
        {
            "contract_version": "1.0",
            "request_id": "req_AUDIT_OUTBOX",
            "trace_id": "trace_AUDIT_OUTBOX",
            "source": "BUSINESS_SERVICE",
            "auth_context": {
                "tenant_id": "tenant_demo",
                "biz_domain": "demo",
                "actor": {"id": "svc_demo", "type": "SERVICE"},
            },
            "operation": operation.value,
            "resource": {
                "target": "POSTGRESQL",
                "type": "DOCUMENT_RECORD",
                "name": "record",
                "resource_id": "doc_audit",
            },
            "payload": {
                "data": {"id": "doc_audit", "title": "audit"},
                "query": {},
                "options": {},
            },
            "idempotency_key": "idem_AUDIT_OUTBOX" if operation in {Operation.CREATE} else None,
            "transaction": {"mode": "LOCAL", "isolation": "READ_COMMITTED"},
            "timeout_ms": 5000,
            "metadata": {"caller_service": "test"},
        }
    )


def make_context() -> ExecutionContext:
    return ExecutionContext(
        tenant_id="tenant_demo",
        biz_domain="demo",
        subject_id="svc_demo",
        subject_type="SERVICE",
        roles=("writer",),
        permissions=("data:record:write",),
        source="BUSINESS_SERVICE",
        request_id="req_AUDIT_OUTBOX",
        trace_id="trace_AUDIT_OUTBOX",
        authenticated=True,
        credential_source="development",
    )


def make_route() -> RouteDecision:
    definition = ResourceDefinition(
        resource_type="DOCUMENT_RECORD",
        logical_name="record",
        target=DataTarget.POSTGRESQL,
        allowed_operations=frozenset({Operation.CREATE, Operation.GET}),
        read_permission="data:record:read",
        write_permission="data:record:write",
    )
    return RouteDecision(
        route_id="route-1",
        adapter_name="postgresql",
        target=DataTarget.POSTGRESQL,
        logical_resource="record",
        read_write_mode="WRITE",
        timeout_ms=5000,
        transaction_mode=TransactionMode.LOCAL,
        policy_version="test",
        resource_mapping=ResourceMapping(
            tenant_id="tenant_demo",
            biz_domain="demo",
            definition=definition,
            physical_mapping={"logical_table": "document_records"},
        ),
    )


def make_payload(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "trace_id": "trace",
        "tenant_id": "tenant_demo",
        "biz_domain": "demo",
        "actor_id": "svc_demo",
        "actor_type": "SERVICE",
        "source": "BUSINESS_SERVICE",
        "operation": "CREATE",
        "target": "POSTGRESQL",
        "logical_resource_type": "DOCUMENT_RECORD",
        "logical_resource_name": "record",
        "resource_id": "doc_audit",
        "policy_decision": "ALLOW",
        "policy_id": None,
        "result_status": "SUCCEEDED",
        "http_status": 200,
        "error_code": None,
        "retryable": False,
        "latency_ms": 10,
        "metadata_digest": "digest",
    }


def make_change_payload(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "trace_id": "trace",
        "tenant_id": "tenant_demo",
        "biz_domain": "demo",
        "actor_id": "svc_demo",
        "target": "POSTGRESQL",
        "logical_resource_type": "DOCUMENT_RECORD",
        "logical_resource_name": "record",
        "resource_id": "doc_audit",
        "operation": "CREATE",
        "before_digest": None,
        "after_digest": "after",
        "changed_fields": {"fields": ["title"]},
        "result_status": "SUCCEEDED",
        "error_code": None,
    }


async def test_audit_outbox_service_enqueues_access_and_change_events() -> None:
    repo = FakeOutboxRepository()
    service = AuditOutboxService(repo, Settings())
    request = make_request()
    context = make_context()
    route = make_route()

    await service.record_access(request, context, status="SUCCEEDED", code="OK", latency_ms=12)
    await service.record_change(
        request,
        context,
        AdapterResult(status="OK", data={"resource_id": "doc_audit", "title": "audit"}),
        status="SUCCEEDED",
        code="OK",
        route=route,
    )

    assert [event.event_type for event in repo.enqueued] == [
        AuditEventType.ACCESS,
        AuditEventType.CHANGE,
    ]
    assert repo.enqueued[0].target == "POSTGRESQL"
    assert repo.enqueued[1].audit_payload["changed_fields"] == {"fields": ["id", "title"]}


async def test_audit_outbox_service_skips_non_write_or_failed_change_events() -> None:
    repo = FakeOutboxRepository()
    service = AuditOutboxService(repo, Settings())
    context = make_context()
    route = make_route()

    await service.record_change(
        make_request(Operation.GET),
        context,
        AdapterResult(status="OK", data={"resource_id": "doc_audit"}),
        status="SUCCEEDED",
        code="OK",
        route=route,
    )
    await service.record_change(
        make_request(),
        context,
        AdapterResult(status="FAILED", data={"resource_id": "doc_audit"}),
        status="FAILED",
        code="ADAPTER_EXECUTION_FAILED",
        route=route,
    )

    assert repo.enqueued == []


async def test_audit_outbox_processor_marks_success_for_claimed_records() -> None:
    record = AuditOutboxRecord(
        id="outbox-1",
        event_id="event-1",
        event_type=AuditEventType.ACCESS,
        audit_payload=make_payload("req_success"),
        attempts=1,
        max_attempts=3,
    )
    repo = FakeOutboxRepository([record])
    session_factory = FakeSessionFactory()
    processor = AuditOutboxProcessor(
        outbox_repository=repo,
        audit_session_factory=session_factory,  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lock_timeout_seconds=30,
    )

    result = await processor.run_once()

    assert result == {"claimed": 1, "processed": 1, "failed": 0}
    assert repo.succeeded == [("outbox-1", "worker-1")]
    assert len(session_factory.added) == 1


async def test_audit_outbox_processor_retries_before_max_attempts() -> None:
    record = AuditOutboxRecord(
        id="outbox-2",
        event_id="event-2",
        event_type=AuditEventType.ACCESS,
        audit_payload=make_payload("req_retry"),
        attempts=1,
        max_attempts=3,
    )
    repo = FakeOutboxRepository([record])
    processor = FailingAuditOutboxProcessor(
        outbox_repository=repo,
        audit_session_factory=FakeSessionFactory(),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lock_timeout_seconds=30,
    )

    result = await processor.run_once()

    assert result == {"claimed": 1, "processed": 0, "failed": 1}
    assert repo.retried[0]["record_id"] == "outbox-2"
    assert repo.retried[0]["error_code"] == "AUDIT_WRITE_FAILED"


async def test_audit_outbox_processor_marks_failed_at_max_attempts() -> None:
    record = AuditOutboxRecord(
        id="outbox-3",
        event_id="event-3",
        event_type=AuditEventType.ACCESS,
        audit_payload=make_payload("req_failed"),
        attempts=3,
        max_attempts=3,
    )
    repo = FakeOutboxRepository([record])
    processor = FailingAuditOutboxProcessor(
        outbox_repository=repo,
        audit_session_factory=FakeSessionFactory(),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lock_timeout_seconds=30,
    )

    result = await processor.run_once()

    assert result == {"claimed": 1, "processed": 0, "failed": 1}
    assert repo.failed[0]["record_id"] == "outbox-3"
    assert repo.failed[0]["error_code"] == "AUDIT_WRITE_FAILED"


async def test_write_formal_audit_supports_change_and_rejects_unknown_event_type() -> None:
    session_factory = FakeSessionFactory()
    processor = AuditOutboxProcessor(
        outbox_repository=FakeOutboxRepository(),
        audit_session_factory=session_factory,  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lock_timeout_seconds=30,
    )

    await processor._write_formal_audit(AuditEventType.ACCESS, make_payload("req_access"))
    await processor._write_formal_audit(AuditEventType.CHANGE, make_change_payload("req_change"))
    with pytest.raises(ValueError):
        await processor._write_formal_audit("UNKNOWN", make_payload("req_unknown"))  # type: ignore[arg-type]

    assert len(session_factory.added) == 2
