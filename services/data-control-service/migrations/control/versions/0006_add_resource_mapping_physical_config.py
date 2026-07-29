"""add resource mapping physical config

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource_mappings",
        sa.Column(
            "physical_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="control_plane",
    )
    op.alter_column(
        "resource_mappings", "physical_config", server_default=None, schema="control_plane"
    )


def downgrade() -> None:
    op.drop_column("resource_mappings", "physical_config", schema="control_plane")
