"""create audit outbox and idempotency recovery fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_outbox",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=True),
        sa.Column("logical_resource_type", sa.String(length=128), nullable=False),
        sa.Column("logical_resource_name", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("audit_payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_audit_outbox_event_id"),
        schema="control_plane",
    )
    op.create_index(
        "ix_audit_outbox_status_retry",
        "audit_outbox",
        ["status", "next_retry_at"],
        schema="control_plane",
    )
    op.create_index(
        "ix_audit_outbox_tenant_biz",
        "audit_outbox",
        ["tenant_id", "biz_domain"],
        schema="control_plane",
    )
    op.create_index(
        "ix_audit_outbox_request_id",
        "audit_outbox",
        ["request_id"],
        schema="control_plane",
    )
    op.create_index(
        "ix_audit_outbox_locked_at",
        "audit_outbox",
        ["locked_at"],
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("business_result_reference", postgresql.JSONB(), nullable=True),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("recovery_strategy", sa.String(length=64), nullable=True),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("max_recovery_attempts", sa.Integer(), nullable=False, server_default="3"),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("last_recovery_at", sa.DateTime(timezone=True), nullable=True),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("recovery_error_code", sa.String(length=64), nullable=True),
        schema="control_plane",
    )
    op.add_column(
        "idempotency_records",
        sa.Column("recovery_metadata", postgresql.JSONB(), nullable=True),
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_column("idempotency_records", "recovery_metadata", schema="control_plane")
    op.drop_column("idempotency_records", "recovery_error_code", schema="control_plane")
    op.drop_column("idempotency_records", "last_recovery_at", schema="control_plane")
    op.drop_column("idempotency_records", "max_recovery_attempts", schema="control_plane")
    op.drop_column("idempotency_records", "recovery_attempts", schema="control_plane")
    op.drop_column("idempotency_records", "recovery_strategy", schema="control_plane")
    op.drop_column("idempotency_records", "business_result_reference", schema="control_plane")
    op.drop_table("audit_outbox", schema="control_plane")
