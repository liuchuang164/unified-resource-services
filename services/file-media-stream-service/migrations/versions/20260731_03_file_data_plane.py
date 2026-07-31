"""Add Phase 3 file resource data-plane persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_03"
down_revision: str | None = "20260730_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_event", sa.Column("offset", sa.Integer(), nullable=True))
    op.add_column("audit_event", sa.Column("length", sa.Integer(), nullable=True))
    op.create_table(
        "file_resource_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("biz_domain", sa.String(64), nullable=False),
        sa.Column("version_id", sa.String(128), nullable=False, unique=True),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "biz_domain", "resource_id", "version"),
    )
    op.create_index(
        "ix_file_version_scope_resource",
        "file_resource_version",
        ["tenant_id", "biz_domain", "resource_id"],
    )
    op.create_table(
        "file_upload_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("biz_domain", sa.String(64), nullable=False),
        sa.Column("upload_id", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("provider_upload_id", sa.String(512), nullable=False),
        sa.Column("upload_reference", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aborted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("tenant_id", "biz_domain", "upload_id"),
    )
    op.create_index(
        "ix_file_upload_scope_resource",
        "file_upload_session",
        ["tenant_id", "biz_domain", "resource_id"],
    )


def downgrade() -> None:
    op.drop_table("file_upload_session")
    op.drop_table("file_resource_version")
    op.drop_column("audit_event", "length")
    op.drop_column("audit_event", "offset")
