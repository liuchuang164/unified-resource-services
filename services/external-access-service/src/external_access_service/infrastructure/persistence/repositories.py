from datetime import UTC, datetime
from uuid import uuid4

from external_access_service.infrastructure.observability.redaction import redact


class PersistentAuditRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    @property
    def events(self) -> list[dict[str, object]]:
        return self.records

    async def record(self, event: dict[str, object]) -> None:
        safe = redact(event)
        safe.setdefault("id", str(uuid4()))
        safe.setdefault("created_at", datetime.now(UTC).isoformat())
        self.records.append(safe)

    async def write(self, event: dict[str, object]) -> None:
        await self.record(event)

    async def query_by_tenant(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        operation: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            record
            for record in self.records
            if record.get("tenant_id") == tenant_id
            and record.get("biz_domain") == biz_domain
            and (operation is None or record.get("operation") == operation)
            and (status is None or record.get("result_status") == status)
        ]

    async def query_by_request_id(
        self, *, tenant_id: str, biz_domain: str, request_id: str
    ) -> list[dict[str, object]]:
        return [
            record
            for record in await self.query_by_tenant(tenant_id=tenant_id, biz_domain=biz_domain)
            if record.get("request_id") == request_id
        ]


class UsageRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record_usage(self, record: dict[str, object]) -> None:
        safe = redact(record)
        safe.setdefault("id", str(uuid4()))
        safe.setdefault("created_at", datetime.now(UTC).isoformat())
        self.records.append(safe)

    async def query_usage(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        operation: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for record in self.records:
            if record.get("tenant_id") != tenant_id or record.get("biz_domain") != biz_domain:
                continue
            if operation is not None and record.get("operation") != operation:
                continue
            if provider is not None and record.get("provider") != provider:
                continue
            key = (str(record["operation"]), str(record["provider"]))
            item = grouped.setdefault(
                key,
                {
                    "tenant_id": tenant_id,
                    "biz_domain": biz_domain,
                    "operation": record["operation"],
                    "provider": record["provider"],
                    "request_count": 0,
                    "estimated_cost": 0.0,
                },
            )
            current_count = int(str(item["request_count"]))
            record_count = int(str(record["request_count"]))
            current_cost = float(str(item["estimated_cost"]))
            record_cost = float(str(record["estimated_cost"]))
            item["request_count"] = current_count + record_count
            item["estimated_cost"] = current_cost + record_cost
        return list(grouped.values())
