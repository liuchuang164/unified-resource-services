from __future__ import annotations

from dataclasses import dataclass

from data_control_service.infrastructure.minio.records import ObjectStatus
from data_control_service.infrastructure.observability.metrics import metrics_registry
from data_control_service.infrastructure.persistence.repositories.sqlalchemy_object_record import (
    SQLAlchemyObjectRecordRepository,
)


@dataclass(frozen=True)
class ObjectCleanupResult:
    scanned: int
    marked_failed: int
    dry_run: bool


class ObjectCleanupService:
    def __init__(self, repository: SQLAlchemyObjectRecordRepository) -> None:
        self._repository = repository

    async def cleanup_pending_uploads(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_type: str,
        resource_name: str,
        limit: int,
        dry_run: bool,
    ) -> ObjectCleanupResult:
        records = await self._repository.list(
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            resource_type=resource_type,
            resource_name=resource_name,
            status=ObjectStatus.PENDING_UPLOAD,
            limit=limit,
        )
        marked = 0
        if not dry_run:
            for record in records:
                await self._repository.mark_failed(record)
                marked += 1
                metrics_registry.increment("minio_orphan_object_total")
        return ObjectCleanupResult(scanned=len(records), marked_failed=marked, dry_run=dry_run)
