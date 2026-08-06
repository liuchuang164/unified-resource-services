from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for Phase 1 persistence rows."""


class ScopeMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)


class FileResourceRow(ScopeMixin, Base):
    __tablename__ = "file_resource"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "resource_id"),
        Index("ix_file_scope_status", "tenant_id", "biz_domain", "status"),
        Index("ix_file_scope_created", "tenant_id", "biz_domain", "created_at"),
    )
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(128))


class FileResourceVersionRow(ScopeMixin, Base):
    __tablename__ = "file_resource_version"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "resource_id", "version"),
        UniqueConstraint("version_id"),
        Index("ix_file_version_scope_resource", "tenant_id", "biz_domain", "resource_id"),
    )
    version_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FileUploadSessionRow(ScopeMixin, Base):
    __tablename__ = "file_upload_session"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "upload_id"),
        Index("ix_file_upload_scope_resource", "tenant_id", "biz_domain", "resource_id"),
    )
    upload_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_upload_id: Mapped[str] = mapped_column(String(512), nullable=False)
    upload_reference: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed: Mapped[bool] = mapped_column(nullable=False, default=False)
    aborted: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_parts: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    version_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaResourceRow(ScopeMixin, Base):
    __tablename__ = "media_resource"
    __table_args__ = (UniqueConstraint("tenant_id", "biz_domain", "resource_id"),)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    codec: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StreamSessionRow(ScopeMixin, Base):
    __tablename__ = "stream_session"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "session_id"),
        Index("ix_stream_scope_status", "tenant_id", "biz_domain", "status"),
        Index("ix_stream_scope_created", "tenant_id", "biz_domain", "created_at"),
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    caller_id: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endpoint_reference: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy")
    stream_key: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    input_protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    output_protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_server_session_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connection_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DISCONNECTED"
    )
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingJobRow(ScopeMixin, Base):
    __tablename__ = "processing_job"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "job_id"),
        Index("ix_job_scope_status", "tenant_id", "biz_domain", "status"),
        Index("ix_job_scope_created", "tenant_id", "biz_domain", "created_at"),
    )
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    input_resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    output_resource_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    processor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceGrantRow(ScopeMixin, Base):
    __tablename__ = "resource_grant"
    __table_args__ = (UniqueConstraint("tenant_id", "biz_domain", "grant_id"),)
    grant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class AuditEventRow(ScopeMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        UniqueConstraint("audit_id"),
        Index("ix_audit_scope_created", "tenant_id", "biz_domain", "created_at"),
    )
    audit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    caller_type: Mapped[str] = mapped_column(String(32), nullable=False)
    caller_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    session_id: Mapped[str | None] = mapped_column(String(128))
    job_id: Mapped[str | None] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int | None] = mapped_column(Integer)
    length: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRecordRow(ScopeMixin, Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "biz_domain", "caller_id", "operation", "idempotency_key"),
        Index("ix_idem_scope_status", "tenant_id", "biz_domain", "status"),
    )
    caller_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReconciliationRecordRow(Base):
    __tablename__ = "reconciliation_record"
    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StreamEventRow(ScopeMixin, Base):
    __tablename__ = "stream_event"
    __table_args__ = (
        UniqueConstraint("event_id"),
        Index("ix_stream_event_scope_session", "tenant_id", "biz_domain", "session_id"),
        Index("ix_stream_event_scope_timestamp", "tenant_id", "biz_domain", "timestamp"),
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, str]] = mapped_column("metadata", JSON, nullable=False)
