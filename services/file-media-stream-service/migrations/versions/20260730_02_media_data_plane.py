"""Add Phase 2 media data plane metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_02"
down_revision: str | None = "20260729_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stream_session",
        sa.Column("provider_type", sa.String(64), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "stream_session",
        sa.Column("stream_key", sa.String(256), nullable=False, server_default=""),
    )
    op.add_column(
        "stream_session",
        sa.Column("input_protocol", sa.String(32), nullable=False, server_default=""),
    )
    op.add_column(
        "stream_session",
        sa.Column("output_protocol", sa.String(32), nullable=False, server_default=""),
    )
    op.add_column(
        "stream_session",
        sa.Column("endpoint", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "stream_session",
        sa.Column("media_server_session_id", sa.String(256), nullable=False, server_default=""),
    )
    op.add_column(
        "stream_session",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "stream_session",
        sa.Column(
            "connection_state",
            sa.String(32),
            nullable=False,
            server_default="DISCONNECTED",
        ),
    )
    op.add_column(
        "stream_session",
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "stream_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("biz_domain", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False, unique=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_stream_event_scope_session",
        "stream_event",
        ["tenant_id", "biz_domain", "session_id"],
    )
    op.create_index(
        "ix_stream_event_scope_timestamp",
        "stream_event",
        ["tenant_id", "biz_domain", "timestamp"],
    )


def downgrade() -> None:
    op.drop_table("stream_event")
    for column in (
        "fencing_token",
        "connection_state",
        "last_heartbeat_at",
        "media_server_session_id",
        "endpoint",
        "output_protocol",
        "input_protocol",
        "stream_key",
        "provider_type",
    ):
        op.drop_column("stream_session", column)
