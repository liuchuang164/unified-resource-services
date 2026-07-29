"""create resource mappings

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_mappings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_name", sa.String(length=128), nullable=False),
        sa.Column("physical_schema", sa.String(length=128), nullable=False),
        sa.Column("physical_table", sa.String(length=128), nullable=False),
        sa.Column("primary_key_column", sa.String(length=128), nullable=False),
        sa.Column("tenant_column", sa.String(length=128), nullable=False),
        sa.Column("biz_domain_column", sa.String(length=128), nullable=False),
        sa.Column("allowed_operations", postgresql.JSONB(), nullable=False),
        sa.Column("upsert_conflict_columns", postgresql.JSONB(), nullable=False),
        sa.Column("field_allowlist", postgresql.JSONB(), nullable=False),
        sa.Column("filter_allowlist", postgresql.JSONB(), nullable=False),
        sa.Column("sort_allowlist", postgresql.JSONB(), nullable=False),
        sa.Column("max_page_size", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "biz_domain",
            "target",
            "resource_type",
            "resource_name",
            "version",
            name="uq_resource_mapping_version",
        ),
        schema="control_plane",
    )
    op.create_index(
        "ix_resource_mapping_current",
        "resource_mappings",
        ["tenant_id", "biz_domain", "target", "enabled"],
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_table("resource_mappings", schema="control_plane")
