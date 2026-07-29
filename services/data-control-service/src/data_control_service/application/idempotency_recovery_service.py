from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, and_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.ports.idempotency_repository import IdempotencyRepository


class IdempotencyRecoveryService:
    def __init__(
        self,
        *,
        idempotency_repository: IdempotencyRepository,
        target_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._idempotency_repository = idempotency_repository
        self._target_session_factory = target_session_factory

    async def inspect(self, *, limit: int) -> list[dict[str, object]]:
        return await self._idempotency_repository.list_recovery_required(limit)

    async def run_once(self, *, limit: int, dry_run: bool) -> dict[str, int]:
        records = await self.inspect(limit=limit)
        recovered = 0
        failed = 0
        for record in records:
            reference = record.get("business_result_reference")
            if not isinstance(reference, dict):
                failed += 1
                if not dry_run:
                    await self._idempotency_repository.mark_recovery_failed(
                        str(record["id"]),
                        error_code="IDEMPOTENCY_RECOVERY_REQUIRED",
                        recovery_metadata={"reason": "missing_business_result_reference"},
                    )
                continue
            snapshot = await self._response_snapshot_from_target(reference)
            if snapshot is None:
                failed += 1
                if not dry_run:
                    await self._idempotency_repository.mark_recovery_failed(
                        str(record["id"]),
                        error_code="RESOURCE_NOT_FOUND",
                        recovery_metadata={"reason": "target_fact_not_found"},
                    )
                continue
            recovered += 1
            if not dry_run:
                await self._idempotency_repository.mark_recovery_succeeded(
                    str(record["id"]),
                    snapshot,
                    recovery_metadata={"reason": "target_fact_verified"},
                )
        return {"inspected": len(records), "recovered": recovered, "failed": failed}

    async def _response_snapshot_from_target(
        self, reference: dict[str, object]
    ) -> dict[str, object] | None:
        if reference.get("target") != "POSTGRESQL":
            return None
        table = self._platform_records_table()
        tenant_id = str(reference.get("tenant_id") or "")
        biz_domain = str(reference.get("biz_domain") or "")
        resource_id = reference.get("resource_id")
        external_id = reference.get("external_id")
        statement = select(table).where(
            and_(
                table.c.tenant_id == tenant_id,
                table.c.biz_domain == biz_domain,
                table.c.deleted_at.is_(None),
            )
        )
        if resource_id:
            statement = statement.where(table.c.id == str(resource_id))
        elif external_id:
            statement = statement.where(table.c.external_id == str(external_id))
        else:
            return None
        async with self._target_session_factory() as session:
            row = (await session.execute(statement)).mappings().first()
        if row is None:
            return None
        return {
            "request_id": "recovered",
            "trace_id": "recovered",
            "success": True,
            "code": "OK",
            "message": "success",
            "data": {"resource_id": str(row["id"]), "external_id": row["external_id"]},
            "meta": {
                "adapter": "postgresql",
                "duration_ms": 0,
                "affected_count": int(str(reference.get("affected_count") or "1")),
                "resource_version": str(row["version"]),
                "idempotency_replayed": False,
                "recovered": True,
            },
        }

    @staticmethod
    def _platform_records_table() -> Table:
        metadata = MetaData()
        return Table(
            "platform_records",
            metadata,
            Column("id", PG_UUID(as_uuid=False), primary_key=True),
            Column("tenant_id", String(64), nullable=False),
            Column("biz_domain", String(64), nullable=False),
            Column("external_id", String(128), nullable=False),
            Column("record_type", String(128), nullable=False),
            Column("title", String(512)),
            Column("content", String),
            Column("attributes", JSONB),
            Column("version", Integer, nullable=False),
            Column("created_at", DateTime(timezone=True)),
            Column("updated_at", DateTime(timezone=True)),
            Column("deleted_at", DateTime(timezone=True)),
            schema="data_target",
        )
