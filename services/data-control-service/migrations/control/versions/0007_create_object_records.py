"""create object records

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_records",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("logical_object_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_name", sa.String(length=128), nullable=False),
        sa.Column("bucket_reference", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("object_key_digest", sa.String(length=64), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("etag", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("upload_mode", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "resource_type",
            "resource_name",
            "logical_object_id",
            name="uq_object_records_scope",
        ),
        schema="control_plane",
    )
    op.create_index(
        "ix_object_records_scope_status",
        "object_records",
        ["tenant_id", "biz_domain", "resource_type", "resource_name", "status"],
        schema="control_plane",
    )
    op.create_index(
        "ix_object_records_created",
        "object_records",
        ["tenant_id", "biz_domain", "created_at"],
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_index("ix_object_records_created", table_name="object_records", schema="control_plane")
    op.drop_index(
        "ix_object_records_scope_status", table_name="object_records", schema="control_plane"
    )
    op.drop_table("object_records", schema="control_plane")
