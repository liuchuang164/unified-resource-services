"""Complete Phase 3.1 upload and version persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_04"
down_revision: str | None = "20260731_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_resource", sa.Column("current_version_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "file_resource_version",
        sa.Column(
            "mime_type",
            sa.String(128),
            nullable=False,
            server_default="application/octet-stream",
        ),
    )
    op.alter_column("file_resource_version", "checksum", nullable=True)
    op.add_column(
        "file_upload_session",
        sa.Column("status", sa.String(32), nullable=False, server_default="INIT"),
    )
    op.add_column(
        "file_upload_session",
        sa.Column("total_parts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "file_upload_session",
        sa.Column("uploaded_parts", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "file_upload_session", sa.Column("version_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "file_upload_session",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "file_upload_session",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_file_upload_scope_status",
        "file_upload_session",
        ["tenant_id", "biz_domain", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_upload_scope_status", table_name="file_upload_session")
    op.drop_column("file_upload_session", "updated_at")
    op.drop_column("file_upload_session", "created_at")
    op.drop_column("file_upload_session", "version_id")
    op.drop_column("file_upload_session", "uploaded_parts")
    op.drop_column("file_upload_session", "total_parts")
    op.drop_column("file_upload_session", "status")
    # The previous schema cannot represent an upload-in-progress version. Preserve
    # rollback operability with an explicit unknown checksum marker before restoring
    # its NOT NULL constraint.
    op.execute(
        sa.text(
            "UPDATE file_resource_version "
            "SET checksum = repeat('0', 64) "
            "WHERE checksum IS NULL"
        )
    )
    op.alter_column("file_resource_version", "checksum", nullable=False)
    op.drop_column("file_resource_version", "mime_type")
    op.drop_column("file_resource", "current_version_id")
