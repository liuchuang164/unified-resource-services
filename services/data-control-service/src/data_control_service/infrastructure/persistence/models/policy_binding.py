from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from data_control_service.infrastructure.persistence.models.base import CONTROL_SCHEMA, Base


class PolicyBindingModel(Base):
    __tablename__ = "policy_bindings"
    __table_args__ = (
        Index("ix_policy_binding_scope", "tenant_id", "biz_domain", "enabled"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_pattern: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    permission: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effect: Mapped[str] = mapped_column(String(16), nullable=False)
    constraints: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
