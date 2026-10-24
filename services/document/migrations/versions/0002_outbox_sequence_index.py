"""Match the unique indexed journal cursor without rewriting the applied initial revision."""

from alembic import op

revision = "document_0002"
down_revision = "document_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("outbox_sequence_key", "outbox", schema="document", type_="unique")
    op.drop_index("ix_document_outbox_sequence", table_name="outbox", schema="document")
    op.create_index(
        "ix_document_outbox_sequence", "outbox", ["sequence"], unique=True, schema="document"
    )


def downgrade():
    raise RuntimeError("Document downgrade requires an explicit reviewed data migration")
