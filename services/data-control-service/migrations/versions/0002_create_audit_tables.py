"""create audit tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_audit_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=True),
        sa.Column("logical_resource_type", sa.String(length=128), nullable=False),
        sa.Column("logical_resource_name", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=True),
        sa.Column("policy_decision", sa.String(length=32), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("metadata_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="control_plane",
    )
    op.create_index(
        "ix_access_audit_request_id", "access_audit_logs", ["request_id"], schema="control_plane"
    )
    op.create_index(
        "ix_access_audit_trace_id", "access_audit_logs", ["trace_id"], schema="control_plane"
    )
    op.create_index(
        "ix_access_audit_tenant_created",
        "access_audit_logs",
        ["tenant_id", "created_at"],
        schema="control_plane",
    )
    op.create_table(
        "change_audit_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("logical_resource_type", sa.String(length=128), nullable=False),
        sa.Column("logical_resource_name", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("before_digest", sa.String(length=64), nullable=True),
        sa.Column("after_digest", sa.String(length=64), nullable=True),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="control_plane",
    )
    op.create_index(
        "ix_change_audit_request_id", "change_audit_logs", ["request_id"], schema="control_plane"
    )
    op.create_index(
        "ix_change_audit_tenant_created",
        "change_audit_logs",
        ["tenant_id", "created_at"],
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_table("change_audit_logs", schema="control_plane")
    op.drop_table("access_audit_logs", schema="control_plane")
