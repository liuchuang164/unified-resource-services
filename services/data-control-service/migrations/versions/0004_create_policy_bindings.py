"""create policy bindings

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_bindings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("biz_domain", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_pattern", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=True),
        sa.Column("permission", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=True),
        sa.Column("target", sa.String(length=32), nullable=True),
        sa.Column("resource_type", sa.String(length=128), nullable=True),
        sa.Column("resource_name", sa.String(length=128), nullable=True),
        sa.Column("effect", sa.String(length=16), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="control_plane",
    )
    op.create_index(
        "ix_policy_binding_scope",
        "policy_bindings",
        ["tenant_id", "biz_domain", "enabled"],
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_table("policy_bindings", schema="control_plane")
