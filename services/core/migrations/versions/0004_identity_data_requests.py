"""identity_data_requests

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 23:43:14.164382
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "request_type",
            sa.Enum(
                "ACCESS",
                "EXPORT",
                "DELETE",
                name="data_request_type",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_REVIEW",
                "COMPLETED",
                "REJECTED",
                name="data_request_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        "ix_core_data_requests_user_id_id",
        "data_requests",
        ["user_id", "id"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("ix_core_data_requests_user_id_id", table_name="data_requests", schema="core")
    op.drop_table("data_requests", schema="core")
