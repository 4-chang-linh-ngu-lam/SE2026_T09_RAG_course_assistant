"""Add separate Student activation/recovery purposes, preserving existing token history."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "one_time_tokens",
        "purpose",
        existing_type=sa.String(18),
        type_=sa.String(22),
        schema="core",
    )
    op.drop_constraint("token_purpose", "one_time_tokens", schema="core", type_="check")
    op.create_check_constraint(
        "token_purpose",
        "one_time_tokens",
        "purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET', 'ADMIN_INVITATION', "
        "'STUDENT_ACTIVATION', 'STUDENT_PASSWORD_RESET')",
        schema="core",
    )


def downgrade() -> None:
    # New-purpose records block downgrade instead of silently removing recovery history.
    op.drop_constraint("token_purpose", "one_time_tokens", schema="core", type_="check")
    op.create_check_constraint(
        "token_purpose",
        "one_time_tokens",
        "purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET', 'ADMIN_INVITATION')",
        schema="core",
    )
    op.alter_column(
        "one_time_tokens",
        "purpose",
        existing_type=sa.String(22),
        type_=sa.String(18),
        schema="core",
    )
