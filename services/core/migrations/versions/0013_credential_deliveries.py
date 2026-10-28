"""Track retryable credential-email delivery without storing raw tokens.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "token_id",
            sa.Uuid(),
            sa.ForeignKey("core.one_time_tokens.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','DELIVERED','CANCELLED','NEEDS_REISSUE')",
            name="ck_credential_delivery_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_credential_delivery_attempts"),
        schema="core",
    )
    op.create_index(
        "idx_credential_delivery_pending",
        "credential_deliveries",
        ["status", "available_at"],
        schema="core",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM core.credential_deliveries)")):
        raise RuntimeError("Preserve credential delivery history before downgrade")
    op.drop_index(
        "idx_credential_delivery_pending",
        table_name="credential_deliveries",
        schema="core",
    )
    op.drop_table("credential_deliveries", schema="core")
