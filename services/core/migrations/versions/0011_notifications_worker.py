"""Notification inbox and retryable outbox envelope. Never rewrite 0009.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        schema="core",
    )
    op.add_column(
        "outbox_events",
        sa.Column("aggregate_version", sa.BigInteger(), nullable=True),
        schema="core",
    )
    op.add_column(
        "outbox_events",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        schema="core",
    )
    op.add_column(
        "outbox_events",
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="core",
    )
    op.add_column(
        "outbox_events", sa.Column("last_error_code", sa.String(64), nullable=True), schema="core"
    )
    for name, expression in (
        ("ck_outbox_schema_version", "schema_version >= 1"),
        ("ck_outbox_attempts", "attempts >= 0"),
        ("ck_outbox_aggregate_version", "aggregate_version IS NULL OR aggregate_version >= 1"),
    ):
        op.create_check_constraint(name, "outbox_events", expression, schema="core")
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "recipient_id",
            sa.Uuid(),
            sa.ForeignKey("core.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.create_index(
        "idx_notifications_recipient_created",
        "notifications",
        ["recipient_id", sa.text("created_at DESC")],
        schema="core",
    )
    op.create_index(
        "idx_notifications_recipient_sequence",
        "notifications",
        ["recipient_id", sa.text("sequence DESC")],
        schema="core",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM core.notifications)")):
        raise RuntimeError("Downgrade would discard notifications; preserve inbox data first")
    op.drop_table("notifications", schema="core")
    for name in ("ck_outbox_schema_version", "ck_outbox_attempts", "ck_outbox_aggregate_version"):
        op.drop_constraint(name, "outbox_events", type_="check", schema="core")
    for name in (
        "schema_version",
        "aggregate_version",
        "attempts",
        "available_at",
        "last_error_code",
    ):
        op.drop_column("outbox_events", name, schema="core")
