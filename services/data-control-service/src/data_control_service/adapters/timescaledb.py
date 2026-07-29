from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    DataAdapter,
    reject_client_scope,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


@dataclass
class _Point:
    timestamp: datetime
    tenant_id: str
    biz_domain: str
    metric: str
    value: float
    tags: dict[str, object]


class InMemoryTimescaleDBAdapter(DataAdapter):
    name = "timescaledb"
    target = DataTarget.TIMESCALEDB

    def __init__(self, max_query_days: int = 31, max_return: int = 1000) -> None:
        self._points: list[_Point] = []
        self._max_query_span = timedelta(days=max_query_days)
        self._max_return = max_return

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH}
            ),
            supports_transactions=True,
            supports_atomic_transaction=True,
            supports_cursor_pagination=True,
            timeout_ms=5000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        tenant_id, biz_domain = command.scope
        if command.operation == Operation.CREATE:
            self._points.append(
                self._parse_point(command.validated_payload.get("data", {}), tenant_id, biz_domain)
            )
            return AdapterResult(status="OK", data={"created": 1}, affected_count=1)
        if command.operation == Operation.BATCH:
            items = command.validated_payload.get("data", {}).get("items", [])
            for item in items:
                self._points.append(self._parse_point(item, tenant_id, biz_domain))
            return AdapterResult(
                status="OK", data={"created": len(items)}, affected_count=len(items)
            )
        if command.operation in {Operation.LIST, Operation.SEARCH}:
            query = command.validated_payload.get("query", {})
            start = _parse_datetime(query.get("start"))
            end = _parse_datetime(query.get("end"))
            if start is None or end is None or end < start or end - start > self._max_query_span:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "invalid time range")
            points = [
                point
                for point in self._points
                if point.tenant_id == tenant_id
                and point.biz_domain == biz_domain
                and start <= point.timestamp <= end
            ]
            points.sort(key=lambda point: point.timestamp)
            data = [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "metric": point.metric,
                    "value": point.value,
                    "tags": point.tags,
                }
                for point in points[: self._max_return]
            ]
            return AdapterResult(
                status="OK",
                data=data,
                affected_count=len(data),
                has_more=len(points) > self._max_return,
            )
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    @staticmethod
    def _parse_point(data: dict[str, Any], tenant_id: str, biz_domain: str) -> _Point:
        reject_client_scope(data)
        timestamp = _parse_datetime(data.get("timestamp"))
        if timestamp is None:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "timestamp is required")
        return _Point(
            timestamp=timestamp,
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            metric=str(data.get("metric") or "default"),
            value=_required_float(data.get("value")),
            tags=dict(data.get("tags", {})),
        )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _required_float(value: object | None) -> float:
    if not isinstance(value, int | float | str):
        raise DataControlError("REQUEST_SCHEMA_INVALID", "value is required")
    return float(value)
