"""Support manually reviewed data correction requests without changing history."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "data_requests",
        "request_type",
        existing_type=sa.String(6),
        type_=sa.String(10),
        schema="core",
    )
    op.drop_constraint("data_request_type", "data_requests", schema="core", type_="check")
    op.create_check_constraint(
        "data_request_type",
        "data_requests",
        "request_type IN ('ACCESS', 'EXPORT', 'CORRECTION', 'DELETE')",
        schema="core",
    )


def downgrade() -> None:
    # Existing CORRECTION records deliberately prevent downgrade instead of being deleted.
    op.drop_constraint("data_request_type", "data_requests", schema="core", type_="check")
    op.create_check_constraint(
        "data_request_type",
        "data_requests",
        "request_type IN ('ACCESS', 'EXPORT', 'DELETE')",
        schema="core",
    )
    op.alter_column(
        "data_requests",
        "request_type",
        existing_type=sa.String(10),
        type_=sa.String(6),
        schema="core",
    )
