from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from data_control_service.infrastructure.persistence.models.base import CONTROL_SCHEMA, Base


class AccessAuditLogModel(Base):
    __tablename__ = "access_audit_logs"
    __table_args__ = (
        Index("ix_access_audit_request_id", "request_id"),
        Index("ix_access_audit_trace_id", "trace_id"),
        Index("ix_access_audit_tenant_created", "tenant_id", "created_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str | None] = mapped_column(String(32), nullable=True)
    logical_resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    logical_resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
