import asyncio

from data_control_service.application.idempotency_service import IdempotencyService
from data_control_service.config.settings import Settings
from data_control_service.contracts.request import DataRequest
from data_control_service.contracts.response import DataResponse
from data_control_service.domain.models import ExecutionContext
from data_control_service.infrastructure.idempotency.in_memory import InMemoryIdempotencyRepository
from tests.integration.test_dispatch_pipeline import base_request


def context(tenant: str = "tenant_demo", domain: str = "demo") -> ExecutionContext:
    return ExecutionContext(
        tenant_id=tenant,
        biz_domain=domain,
        subject_id="svc_demo",
        subject_type="SERVICE",
        roles=(),
        permissions=("data:record:read", "data:record:write"),
        source="BUSINESS_SERVICE",
        request_id="req_test",
        trace_id="trace_test",
        authenticated=True,
        credential_source="test",
    )


async def test_same_scope_claim_is_atomic() -> None:
    service = IdempotencyService(InMemoryIdempotencyRepository(), Settings())
    request = DataRequest.model_validate(base_request())

    async def claim_once() -> str | None:
        record_id, replay = await service.claim(request, context())
        return record_id if replay is None else "replay"

    results = await asyncio.gather(*(claim_once() for _ in range(20)), return_exceptions=True)
    claimed = [item for item in results if isinstance(item, str) and item.startswith("idem_")]
    in_progress = [item for item in results if item.__class__.__name__ == "DataControlError"]
    assert len(claimed) == 1
    assert len(in_progress) == 19


async def test_succeeded_request_replays() -> None:
    service = IdempotencyService(InMemoryIdempotencyRepository(), Settings())
    request = DataRequest.model_validate(base_request())
    record_id, replay = await service.claim(request, context())
    assert replay is None
    await service.succeed(
        record_id,
        request,
        DataResponse(
            request_id="req_01J_TEST",
            trace_id="trace_01J_TEST",
            success=True,
            code="OK",
            message="success",
            data={"resource_id": "doc_001"},
        ),
    )
    _, replay = await service.claim(request, context())
    assert replay is not None
    assert replay.meta["idempotency_replayed"] is True


async def test_same_key_different_tenant_does_not_conflict() -> None:
    service = IdempotencyService(InMemoryIdempotencyRepository(), Settings())
    request = DataRequest.model_validate(base_request())
    first, _ = await service.claim(request, context("tenant_demo", "demo"))
    second, _ = await service.claim(request, context("tenant_other", "demo"))
    assert first is not None
    assert second is not None


async def test_same_key_different_biz_domain_does_not_conflict() -> None:
    service = IdempotencyService(InMemoryIdempotencyRepository(), Settings())
    request = DataRequest.model_validate(base_request())
    first, _ = await service.claim(request, context("tenant_demo", "demo"))
    second, _ = await service.claim(request, context("tenant_demo", "other"))
    assert first is not None
    assert second is not None


async def test_failed_record_can_be_retried() -> None:
    service = IdempotencyService(InMemoryIdempotencyRepository(), Settings())
    request = DataRequest.model_validate(base_request())
    record_id, _ = await service.claim(request, context())
    await service.fail(record_id, request, "ADAPTER_TIMEOUT")
    retry_record_id, replay = await service.claim(request, context())
    assert retry_record_id == record_id
    assert replay is None
