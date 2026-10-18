"""Add Student identifiers and school context while preserving legacy accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=True, schema="core")
    op.add_column("users", sa.Column("username", sa.String(200)), schema="core")
    # School is owned by Classroom; its table/assignment contract is not implemented yet.
    op.add_column("users", sa.Column("school_id", sa.Uuid()), schema="core")
    op.add_column("users", sa.Column("activated_at", sa.DateTime(timezone=True)), schema="core")
    op.create_unique_constraint("uq_users_username", "users", ["username"], schema="core")
    op.create_check_constraint(
        "ck_users_username_lowercase", "users", "username = lower(username)", schema="core"
    )
    op.create_index("ix_core_users_school_id", "users", ["school_id"], schema="core")


def downgrade() -> None:
    # Fail before dropping fields when email-free accounts cannot fit the legacy schema.
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=False, schema="core")
    op.drop_index("ix_core_users_school_id", table_name="users", schema="core")
    op.drop_constraint("ck_users_username_lowercase", "users", schema="core", type_="check")
    op.drop_constraint("uq_users_username", "users", schema="core", type_="unique")
    op.drop_column("users", "activated_at", schema="core")
    op.drop_column("users", "school_id", schema="core")
    op.drop_column("users", "username", schema="core")
