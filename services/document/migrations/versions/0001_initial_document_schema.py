import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "document"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("latest_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_rag_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DELETING', 'DELETED')", name="ck_documents_status"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        schema=SCHEMA,
    )
    op.create_index("ix_documents_owner_status", "documents", ["owner_id", "status"], schema=SCHEMA)
    op.create_index(
        "ix_documents_latest_version", "documents", ["latest_version_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_documents_active_rag_version",
        "documents",
        ["active_rag_version_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "document_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", postgresql.CHAR(length=64), nullable=True),
        sa.Column(
            "file_status", sa.String(), server_default=sa.text("'UPLOADING'"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_number_positive"),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_document_versions_size_nonnegative"
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_document_versions_sha256_format",
        ),
        sa.CheckConstraint(
            "file_status IN ('UPLOADING', 'STORED', 'FAILED')",
            name="ck_document_versions_file_status",
        ),
        sa.CheckConstraint(
            "file_status <> 'STORED' OR (storage_key IS NOT NULL AND "
            "original_filename IS NOT NULL AND mime_type IS NOT NULL AND "
            "size_bytes IS NOT NULL AND sha256 IS NOT NULL AND stored_at IS NOT NULL)",
            name="ck_document_versions_stored_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.documents.id"],
            name="fk_document_versions_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_number"
        ),
        sa.UniqueConstraint("id", "document_id", name="uq_document_versions_id_document"),
        sa.UniqueConstraint("storage_key", name="uq_document_versions_storage_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_document_versions_document_created",
        "document_versions",
        ["document_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "document_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classroom_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)",
            name="ck_document_grants_revocation_pair",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.documents.id"],
            name="fk_document_grants_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_grants"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_document_grants_active_document_classroom",
        "document_grants",
        ["document_id", "classroom_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_document_grants_active_classroom",
        "document_grants",
        ["classroom_id", "document_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ai_job_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("index_ref", sa.String(), nullable=True),
        sa.Column(
            "next_action_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED')",
            name="ck_ingestion_jobs_status",
        ),
        sa.CheckConstraint("attempt_number >= 0", name="ck_ingestion_jobs_attempt_nonnegative"),
        sa.CheckConstraint(
            "(lease_until IS NULL AND lease_token IS NULL) OR "
            "(lease_until IS NOT NULL AND lease_token IS NOT NULL)",
            name="ck_ingestion_jobs_lease_pair",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document.document_versions.id"],
            name="fk_ingestion_jobs_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ingestion_jobs_version_attempt",
        "ingestion_jobs",
        ["version_id", "attempt_number"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ingestion_jobs_status_next_action",
        "ingestion_jobs",
        ["status", "next_action_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_ingestion_jobs_ai_job_id", "ingestion_jobs", ["ai_job_id"], schema=SCHEMA)
    op.create_index(
        "uq_ingestion_jobs_active_version",
        "ingestion_jobs",
        ["version_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('PENDING', 'PROCESSING')"),
    )

    op.create_foreign_key(
        "fk_documents_latest_version_same_document",
        "documents",
        "document_versions",
        ["latest_version_id", "id"],
        ["id", "document_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_documents_active_rag_version_same_document",
        "documents",
        "document_versions",
        ["active_rag_version_id", "id"],
        ["id", "document_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline downgrade is disabled because it cannot check for stored data")
    connection = op.get_bind()
    for table_name in ("ingestion_jobs", "document_grants", "document_versions", "documents"):
        has_rows = connection.scalar(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM document.{table_name} LIMIT 1)")
        )
        if has_rows:
            raise RuntimeError("Document schema downgrade is blocked while service data exists")

    op.drop_constraint(
        "fk_documents_latest_version_same_document", "documents", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documents_active_rag_version_same_document",
        "documents",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("ingestion_jobs", schema=SCHEMA)
    op.drop_table("document_grants", schema=SCHEMA)
    op.drop_table("document_versions", schema=SCHEMA)
    op.drop_table("documents", schema=SCHEMA)
