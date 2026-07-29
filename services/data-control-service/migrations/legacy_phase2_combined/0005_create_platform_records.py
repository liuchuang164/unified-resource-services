"""create platform records target table

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
    op.execute("CREATE SCHEMA IF NOT EXISTS data_target")
    op.create_table(
        "platform_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("record_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "external_id",
            name="uq_platform_records_external_scope",
        ),
        schema="data_target",
    )
    op.create_index(
        "ix_platform_records_scope",
        "platform_records",
        ["tenant_id", "biz_domain"],
        schema="data_target",
    )
    op.create_index(
        "ix_platform_records_updated_at", "platform_records", ["updated_at"], schema="data_target"
    )


def downgrade() -> None:
    op.drop_table("platform_records", schema="data_target")
