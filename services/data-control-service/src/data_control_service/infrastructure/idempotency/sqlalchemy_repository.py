from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, select
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from data_control_service.ports.idempotency_repository import (
    IdempotencyClaimResult,
    IdempotencyClaimState,
    IdempotencyRepository,
    IdempotencyScope,
    IdempotencyStatus,
)


class Base(DeclarativeBase):
    pass


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "operation",
            "target",
            "idempotency_key",
            name="uq_idempotency_scope",
        ),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SQLAlchemyIdempotencyRepository(IdempotencyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        scope: IdempotencyScope,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IdempotencyClaimResult:
        from datetime import UTC
        from uuid import uuid4

        now = datetime.now(UTC)
        model = IdempotencyRecordModel(
            record_id=f"idem_{uuid4().hex}",
            tenant_id=scope.tenant_id,
            biz_domain=scope.biz_domain,
            operation=scope.operation.value,
            target=scope.target.value,
            idempotency_key=scope.idempotency_key,
            request_fingerprint=request_fingerprint,
            status=IdempotencyStatus.PROCESSING.value,
            response_snapshot=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            return IdempotencyClaimResult(IdempotencyClaimState.CLAIMED, model.record_id)
        except IntegrityError:
            await self._session.rollback()
            existing = await self._select_for_update(scope)
            if existing is None:
                raise
            if existing.request_fingerprint != request_fingerprint:
                return IdempotencyClaimResult(
                    IdempotencyClaimState.FINGERPRINT_CONFLICT, existing.record_id
                )
            if existing.status == IdempotencyStatus.PROCESSING.value:
                return IdempotencyClaimResult(IdempotencyClaimState.IN_PROGRESS, existing.record_id)
            if existing.status == IdempotencyStatus.SUCCEEDED.value:
                return IdempotencyClaimResult(
                    IdempotencyClaimState.REPLAY_SUCCEEDED,
                    existing.record_id,
                    response_snapshot=existing.response_snapshot,
                )
            return IdempotencyClaimResult(
                IdempotencyClaimState.RETRY_FAILED,
                existing.record_id,
                error_code=existing.error_code,
            )

    async def mark_succeeded(
        self,
        record_id: str,
        response_snapshot: dict[str, object],
    ) -> None:
        record = await self._session.get(IdempotencyRecordModel, record_id)
        if record is not None:
            record.status = IdempotencyStatus.SUCCEEDED.value
            record.response_snapshot = response_snapshot

    async def mark_failed(self, record_id: str, error_code: str) -> None:
        record = await self._session.get(IdempotencyRecordModel, record_id)
        if record is not None:
            record.status = IdempotencyStatus.FAILED.value
            record.error_code = error_code

    async def health(self) -> dict[str, str]:
        return {"status": "ok", "backend": "sqlalchemy"}

    async def _select_for_update(self, scope: IdempotencyScope) -> IdempotencyRecordModel | None:
        result = await self._session.execute(
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
