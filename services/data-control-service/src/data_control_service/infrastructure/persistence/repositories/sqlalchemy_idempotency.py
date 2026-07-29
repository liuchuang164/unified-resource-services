from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper
from data_control_service.infrastructure.persistence.models.idempotency import (
    IdempotencyRecordModel,
)
from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimResult,
    IdempotencyClaimState,
    IdempotencyRepository,
    IdempotencyScope,
    IdempotencyStatus,
)


class SQLAlchemyIdempotencyRepository(IdempotencyRepository):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        processing_timeout_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._processing_timeout_seconds = processing_timeout_seconds

    async def claim(
        self,
        scope: IdempotencyScope,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IdempotencyClaimResult:
        now = datetime.now(UTC)
        record_id = f"idem_{uuid4().hex}"
        owner_token = uuid4().hex
        async with self._session_factory() as session:
            record = IdempotencyRecordModel(
                id=record_id,
                tenant_id=scope.tenant_id,
                biz_domain=scope.biz_domain,
                operation=scope.operation.value,
                target=scope.target.value,
                idempotency_key=scope.idempotency_key,
                request_fingerprint=request_fingerprint,
                status=IdempotencyStatus.PROCESSING.value,
                response_snapshot=None,
                error_code=None,
                owner_token=owner_token,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                processing_started_at=now,
                completed_at=None,
            )
            session.add(record)
            try:
                await session.commit()
                return IdempotencyClaimResult(IdempotencyClaimState.CLAIMED, record_id, owner_token)
            except IntegrityError:
                await session.rollback()
            except Exception as exc:
                raise PostgreSQLErrorMapper.to_error(exc) from exc

        async with self._session_factory() as session:
            async with session.begin():
                existing = await self._select_for_update(session, scope)
                if existing is None:
                    return IdempotencyClaimResult(
                        IdempotencyClaimState.RETRY_FAILED, record_id, owner_token
                    )
                if existing.request_fingerprint != request_fingerprint:
                    return IdempotencyClaimResult(
                        IdempotencyClaimState.FINGERPRINT_CONFLICT, existing.id
                    )
                if existing.status == IdempotencyStatus.SUCCEEDED.value:
                    return IdempotencyClaimResult(
                        IdempotencyClaimState.REPLAY_SUCCEEDED,
                        existing.id,
                        response_snapshot=existing.response_snapshot,
                    )
                if existing.status == IdempotencyStatus.PROCESSING.value:
                    age = (now - existing.processing_started_at).total_seconds()
                    if age < self._processing_timeout_seconds:
                        return IdempotencyClaimResult(
                            IdempotencyClaimState.IN_PROGRESS, existing.id
                        )
                    existing.owner_token = uuid4().hex
                    existing.updated_at = now
                    existing.processing_started_at = now
                    existing.expires_at = expires_at
                    return IdempotencyClaimResult(
                        IdempotencyClaimState.CLAIMED, existing.id, existing.owner_token
                    )
                existing.status = IdempotencyStatus.PROCESSING.value
                existing.owner_token = uuid4().hex
                existing.response_snapshot = None
                existing.updated_at = now
                existing.processing_started_at = now
                existing.expires_at = expires_at
                return IdempotencyClaimResult(
                    IdempotencyClaimState.RETRY_FAILED, existing.id, existing.owner_token
                )

    async def mark_succeeded(
        self,
        record_id: str,
        owner_token: str,
        response_snapshot: dict[str, object],
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                record = await session.get(IdempotencyRecordModel, record_id, with_for_update=True)
                if (
                    record is None
                    or record.owner_token != owner_token
                    or record.status != IdempotencyStatus.PROCESSING.value
                ):
                    return
                record.status = IdempotencyStatus.SUCCEEDED.value
                record.response_snapshot = response_snapshot
                record.error_code = None
                record.updated_at = now
                record.completed_at = now

    async def mark_failed(self, record_id: str, owner_token: str, error_code: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                record = await session.get(IdempotencyRecordModel, record_id, with_for_update=True)
                if (
                    record is None
                    or record.owner_token != owner_token
                    or record.status != IdempotencyStatus.PROCESSING.value
                ):
                    return
                record.status = IdempotencyStatus.FAILED.value
                record.error_code = error_code
                record.updated_at = now
                record.completed_at = now

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            await session.execute(select(IdempotencyRecordModel.id).limit(1))
        return {"status": "ok", "backend": "postgresql"}

    async def _select_for_update(
        self, session: AsyncSession, scope: IdempotencyScope
    ) -> IdempotencyRecordModel | None:
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == scope.tenant_id,
                IdempotencyRecordModel.biz_domain == scope.biz_domain,
                IdempotencyRecordModel.operation == scope.operation.value,
                IdempotencyRecordModel.target == scope.target.value,
                IdempotencyRecordModel.idempotency_key == scope.idempotency_key,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()
