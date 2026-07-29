"""create idempotency records

Revision ID: 0001
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS control_plane")
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("owner_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "operation",
            "target",
            "idempotency_key",
            name="uq_idempotency_scope",
        ),
        schema="control_plane",
    )
    op.create_index(
        "ix_idempotency_expires_at", "idempotency_records", ["expires_at"], schema="control_plane"
    )
    op.create_index(
        "ix_idempotency_status", "idempotency_records", ["status"], schema="control_plane"
    )
    op.create_index(
        "ix_idempotency_tenant_biz",
        "idempotency_records",
        ["tenant_id", "biz_domain"],
        schema="control_plane",
    )
    op.create_index(
        "ix_idempotency_processing_started_at",
        "idempotency_records",
        ["processing_started_at"],
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_table("idempotency_records", schema="control_plane")
