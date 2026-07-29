from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from data_control_service.infrastructure.persistence.models.base import CONTROL_SCHEMA, Base


class ChangeAuditLogModel(Base):
    __tablename__ = "change_audit_logs"
    __table_args__ = (
        Index("ix_change_audit_request_id", "request_id"),
        Index("ix_change_audit_tenant_created", "tenant_id", "created_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    logical_resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    before_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_fields: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
