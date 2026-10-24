"""Preserve authorized historical labels without leaking later private source changes."""

import sqlalchemy as sa
from alembic import op

revision = "document_0003"
down_revision = "document_0002"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("source_notes", "bookmarks"):
        op.add_column(table, sa.Column("document_title", sa.String(200)), schema="document")
        op.add_column(table, sa.Column("class_name", sa.String(200)), schema="document")
        # Legacy rows predate snapshots. Their historical class name is unknowable;
        # preserve the recorded ID rather than inventing a name or reading Core SQL.
        op.execute(
            sa.text(
                f"UPDATE document.{table} AS p SET document_title = d.title, "
                "class_name = p.class_id::text FROM document.documents AS d "
                "WHERE p.document_id = d.id"
            )
        )
        for column in ("document_title", "class_name"):
            op.alter_column(table, column, nullable=False, schema="document")


def downgrade():
    raise RuntimeError("Document downgrade requires an explicit reviewed data migration")
