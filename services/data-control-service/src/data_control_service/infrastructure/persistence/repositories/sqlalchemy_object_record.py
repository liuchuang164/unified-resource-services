from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.infrastructure.minio.records import (
    ObjectRecord,
    ObjectStatus,
    UploadMode,
)
from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper
from data_control_service.infrastructure.persistence.models.object_record import ObjectRecordModel


class SQLAlchemyObjectRecordRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        logical_object_id: str,
        tenant_id: str,
        biz_domain: str,
        resource_type: str,
        resource_name: str,
        bucket_reference: str,
        object_key: str,
        object_key_digest: str,
        safe_filename: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str | None,
        etag: str | None,
        status: ObjectStatus,
        upload_mode: UploadMode,
        created_by: str,
        metadata: dict[str, object],
    ) -> ObjectRecord:
        now = datetime.now(UTC)
        model = ObjectRecordModel(
            id=f"objrec_{uuid4().hex}",
            logical_object_id=logical_object_id,
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            resource_type=resource_type,
            resource_name=resource_name,
            bucket_reference=bucket_reference,
            object_key=object_key,
            object_key_digest=object_key_digest,
            safe_filename=safe_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            etag=etag,
            status=status.value,
            upload_mode=upload_mode.value,
            created_by=created_by,
            metadata_json=metadata,
            created_at=now,
            updated_at=now,
            completed_at=now if status == ObjectStatus.AVAILABLE else None,
            deleted_at=None,
        )
        async with self._session_factory() as session:
            session.add(model)
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise PostgreSQLErrorMapper.to_error(exc) from exc
        return self._to_record(model)

    async def get(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_type: str,
        resource_name: str,
        logical_object_id: str,
    ) -> ObjectRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ObjectRecordModel).where(
                    ObjectRecordModel.tenant_id == tenant_id,
                    ObjectRecordModel.biz_domain == biz_domain,
                    ObjectRecordModel.resource_type == resource_type,
                    ObjectRecordModel.resource_name == resource_name,
                    ObjectRecordModel.logical_object_id == logical_object_id,
                )
            )
            model = result.scalar_one_or_none()
        return self._to_record(model) if model is not None else None

    async def list(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        resource_type: str,
        resource_name: str,
        status: ObjectStatus | None,
        limit: int,
    ) -> list[ObjectRecord]:
        query = select(ObjectRecordModel).where(
            ObjectRecordModel.tenant_id == tenant_id,
            ObjectRecordModel.biz_domain == biz_domain,
            ObjectRecordModel.resource_type == resource_type,
            ObjectRecordModel.resource_name == resource_name,
        )
        if status is not None:
            query = query.where(ObjectRecordModel.status == status.value)
        query = query.order_by(ObjectRecordModel.created_at.desc()).limit(limit)
        async with self._session_factory() as session:
            result = await session.execute(query)
            return [self._to_record(item) for item in result.scalars().all()]

    async def mark_available(
        self,
        record: ObjectRecord,
        *,
        size_bytes: int,
        checksum_sha256: str,
        etag: str | None,
        content_type: str,
    ) -> ObjectRecord:
        return await self._update(
            record,
            status=ObjectStatus.AVAILABLE,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            etag=etag,
            content_type=content_type,
            completed_at=datetime.now(UTC),
        )

    async def mark_delete_pending(self, record: ObjectRecord) -> ObjectRecord:
        return await self._update(record, status=ObjectStatus.DELETE_PENDING)

    async def mark_deleted(self, record: ObjectRecord) -> ObjectRecord:
        now = datetime.now(UTC)
        return await self._update(record, status=ObjectStatus.DELETED, deleted_at=now)

    async def mark_failed(self, record: ObjectRecord) -> ObjectRecord:
        return await self._update(record, status=ObjectStatus.FAILED)

    async def _update(self, record: ObjectRecord, **values: object) -> ObjectRecord:
        async with self._session_factory() as session:
            async with session.begin():
                model = await session.get(ObjectRecordModel, record.id, with_for_update=True)
                if model is None:
                    raise RuntimeError("object record disappeared")
                for key, value in values.items():
                    if key == "status" and isinstance(value, ObjectStatus):
                        setattr(model, key, value.value)
                    else:
                        setattr(model, key, value)
                model.updated_at = datetime.now(UTC)
            await session.refresh(model)
            return self._to_record(model)

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            await session.execute(select(ObjectRecordModel.id).limit(1))
        return {"status": "ok", "backend": "postgresql"}

    @staticmethod
    def _to_record(model: ObjectRecordModel) -> ObjectRecord:
        return ObjectRecord(
            id=model.id,
            logical_object_id=model.logical_object_id,
            tenant_id=model.tenant_id,
            biz_domain=model.biz_domain,
            resource_type=model.resource_type,
            resource_name=model.resource_name,
            bucket_reference=model.bucket_reference,
            object_key=model.object_key,
            object_key_digest=model.object_key_digest,
            safe_filename=model.safe_filename,
            content_type=model.content_type,
            size_bytes=model.size_bytes,
            checksum_sha256=model.checksum_sha256,
            etag=model.etag,
            status=ObjectStatus(model.status),
            upload_mode=UploadMode(model.upload_mode),
            created_by=model.created_by,
            metadata=dict(model.metadata_json or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            deleted_at=model.deleted_at,
        )
