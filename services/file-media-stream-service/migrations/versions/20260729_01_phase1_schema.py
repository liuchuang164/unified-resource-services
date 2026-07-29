"""Phase 1 production persistence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("biz_domain", sa.String(64), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "file_resource",
        *_scope_columns(),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("owner_type", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("normalized_filename", sa.String(180), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "resource_id"),
    )
    _scope_indexes("file", "file_resource", "resource_id")
    op.create_table(
        "media_resource",
        *_scope_columns(),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("codec", sa.String(64)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("sample_rate", sa.Integer()),
        sa.Column("channels", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "resource_id"),
    )
    op.create_table(
        "stream_session",
        *_scope_columns(),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("caller_id", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endpoint_reference", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "session_id"),
    )
    _scope_indexes("stream", "stream_session", "session_id")
    op.create_table(
        "processing_job",
        *_scope_columns(),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("input_resource_id", sa.String(128), nullable=False),
        sa.Column("output_resource_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("processor_type", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "job_id"),
    )
    _scope_indexes("job", "processing_job", "job_id")
    op.create_table(
        "resource_grant",
        *_scope_columns(),
        sa.Column("grant_id", sa.String(128), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "grant_id"),
    )
    op.create_table(
        "audit_event",
        *_scope_columns(),
        sa.Column("audit_id", sa.String(128), nullable=False, unique=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("caller_type", sa.String(32), nullable=False),
        sa.Column("caller_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("session_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_audit_scope_created",
        "audit_event",
        ["tenant_id", "biz_domain", "created_at"],
    )
    op.create_table(
        "idempotency_record",
        *_scope_columns(),
        sa.Column("caller_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response_snapshot", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "caller_id",
            "operation",
            "idempotency_key",
        ),
    )
    op.create_index(
        "ix_idem_scope_status",
        "idempotency_record",
        ["tenant_id", "biz_domain", "status"],
    )
    op.create_table(
        "reconciliation_record",
        sa.Column("key", sa.String(256), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("biz_domain", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _scope_indexes(prefix: str, table: str, identifier: str) -> None:
    op.create_index(
        f"ix_{prefix}_scope_id", table, ["tenant_id", "biz_domain", identifier], unique=True
    )
    op.create_index(f"ix_{prefix}_scope_status", table, ["tenant_id", "biz_domain", "status"])
    op.create_index(f"ix_{prefix}_scope_created", table, ["tenant_id", "biz_domain", "created_at"])


def downgrade() -> None:
    for table in (
        "reconciliation_record",
        "idempotency_record",
        "audit_event",
        "resource_grant",
        "processing_job",
        "stream_session",
        "media_resource",
        "file_resource",
    ):
        op.drop_table(table)
