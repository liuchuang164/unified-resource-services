from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data_control_service.infrastructure.persistence.models.base import TARGET_SCHEMA, Base


class PlatformRecordModel(Base):
    __tablename__ = "platform_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "external_id",
            name="uq_platform_records_external_scope",
        ),
        Index("ix_platform_records_scope", "tenant_id", "biz_domain"),
        Index("ix_platform_records_updated_at", "updated_at"),
        {"schema": TARGET_SCHEMA},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
