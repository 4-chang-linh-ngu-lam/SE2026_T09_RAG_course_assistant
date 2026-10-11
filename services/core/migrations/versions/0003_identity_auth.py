"""identity_auth

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11 22:23:37.925723
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_VERIFICATION",
                "ACTIVE",
                "LOCKED",
                name="user_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            server_default="PENDING_VERIFICATION",
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.CheckConstraint("session_version >= 1", name="ck_users_session_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema="core",
    )
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_hash"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_auth_sessions_family_id"),
        "auth_sessions",
        ["family_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_auth_sessions_user_id"),
        "auth_sessions",
        ["user_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "one_time_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "EMAIL_VERIFICATION",
                "PASSWORD_RESET",
                "ADMIN_INVITATION",
                name="token_purpose",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_one_time_tokens_user_id"),
        "one_time_tokens",
        ["user_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "role_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "STUDENT",
                "LECTURER",
                "ADMIN",
                name="system_role",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role", name="uq_role_assignments_user_role"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("role_assignments", schema="core")
    op.drop_index(
        op.f("ix_core_one_time_tokens_user_id"), table_name="one_time_tokens", schema="core"
    )
    op.drop_table("one_time_tokens", schema="core")
    op.drop_index(op.f("ix_core_auth_sessions_user_id"), table_name="auth_sessions", schema="core")
    op.drop_index(
        op.f("ix_core_auth_sessions_family_id"), table_name="auth_sessions", schema="core"
    )
    op.drop_table("auth_sessions", schema="core")
    op.drop_table("users", schema="core")
