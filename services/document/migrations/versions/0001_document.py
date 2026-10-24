"""Document-owned initial schema. No Core tables or cross-service foreign keys."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "document_0001"
down_revision = None
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "documents",
        *common(),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("owner_name", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("serving_version", sa.Integer()),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.CheckConstraint("revision > 0"),
        schema="document",
    )
    op.create_index(
        "ix_document_documents_school_id", "documents", ["school_id"], schema="document"
    )
    op.create_index("ix_document_documents_owner_id", "documents", ["owner_id"], schema="document")
    op.create_table(
        "document_versions",
        *common(),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.documents.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("content", JSONB()),
        sa.UniqueConstraint("document_id", "number"),
        sa.CheckConstraint("number > 0 AND size > 0 AND generation >= 0"),
        sa.CheckConstraint("status IN ('PENDING','PROCESSING','READY','FAILED')"),
        schema="document",
    )
    for column in ("document_id", "status", "lease_until"):
        op.create_index(
            f"ix_document_document_versions_{column}",
            "document_versions",
            [column],
            schema="document",
        )
    op.create_table(
        "class_document_grants",
        *common(),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.documents.id"), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "class_id"),
        sa.CheckConstraint("revision > 0"),
        schema="document",
    )
    for column in ("document_id", "class_id"):
        op.create_index(
            f"ix_document_class_document_grants_{column}",
            "class_document_grants",
            [column],
            schema="document",
        )
    op.create_index(
        "ix_document_grant_active",
        "class_document_grants",
        ["class_id", "active"],
        schema="document",
    )
    op.create_table(
        "source_notes",
        *common(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.documents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("locator_id", sa.String(16), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("user_id", "client_request_id"),
        schema="document",
    )
    for column in ("user_id", "document_id", "class_id"):
        op.create_index(
            f"ix_document_source_notes_{column}", "source_notes", [column], schema="document"
        )
    op.create_table(
        "bookmarks",
        *common(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.documents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("locator_id", sa.String(16), nullable=False),
        sa.UniqueConstraint("user_id", "document_id", "class_id", "version", "locator_id"),
        schema="document",
    )
    op.create_index("ix_document_bookmarks_user_id", "bookmarks", ["user_id"], schema="document")
    op.create_table(
        "upload_receipts",
        *common(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.documents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "request_id"),
        schema="document",
    )
    op.create_table(
        "outbox",
        *common(),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("notification_payload", sa.Boolean(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        schema="document",
    )
    op.create_index("ix_document_outbox_sequence", "outbox", ["sequence"], schema="document")


def downgrade():
    # No implicit destructive downgrade of durable user files/notes.
    raise RuntimeError("Document downgrade requires an explicit reviewed data migration")
