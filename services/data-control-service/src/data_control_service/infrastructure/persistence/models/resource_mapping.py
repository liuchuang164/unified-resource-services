from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from data_control_service.infrastructure.persistence.models.base import CONTROL_SCHEMA, Base


class ResourceMappingModel(Base):
    __tablename__ = "resource_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "target",
            "resource_type",
            "resource_name",
            "version",
            name="uq_resource_mapping_version",
        ),
        Index("ix_resource_mapping_current", "tenant_id", "biz_domain", "target", "enabled"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    physical_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    physical_table: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_key_column: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_column: Mapped[str] = mapped_column(String(128), nullable=False)
    biz_domain_column: Mapped[str] = mapped_column(String(128), nullable=False)
    allowed_operations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    upsert_conflict_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    field_allowlist: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    filter_allowlist: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sort_allowlist: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    physical_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    max_page_size: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
