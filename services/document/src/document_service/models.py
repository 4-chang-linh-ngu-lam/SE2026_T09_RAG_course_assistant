from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from document_service.db import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'DELETING', 'DELETED')",
            name="ck_documents_status",
        ),
        PrimaryKeyConstraint("id", name="pk_documents"),
        ForeignKeyConstraint(
            ["latest_version_id", "id"],
            ["document.document_versions.id", "document.document_versions.document_id"],
            name="fk_documents_latest_version_same_document",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["active_rag_version_id", "id"],
            ["document.document_versions.id", "document.document_versions.document_id"],
            name="fk_documents_active_rag_version_same_document",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_documents_owner_status", "owner_id", "status"),
        Index("ix_documents_latest_version", "latest_version_id"),
        Index("ix_documents_active_rag_version", "active_rag_version_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'ACTIVE'"))
    latest_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    active_rag_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_number"
        ),
        UniqueConstraint("id", "document_id", name="uq_document_versions_id_document"),
        UniqueConstraint("storage_key", name="uq_document_versions_storage_key"),
        PrimaryKeyConstraint("id", name="pk_document_versions"),
        CheckConstraint("version_number > 0", name="ck_document_versions_number_positive"),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_document_versions_size_nonnegative"
        ),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_document_versions_sha256_format",
        ),
        CheckConstraint(
            "file_status IN ('UPLOADING', 'STORED', 'FAILED')",
            name="ck_document_versions_file_status",
        ),
        CheckConstraint(
            "file_status <> 'STORED' OR (storage_key IS NOT NULL AND "
            "original_filename IS NOT NULL AND mime_type IS NOT NULL AND "
            "size_bytes IS NOT NULL AND sha256 IS NOT NULL AND stored_at IS NOT NULL)",
            name="ck_document_versions_stored_metadata",
        ),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.documents.id"],
            name="fk_document_versions_document",
            ondelete="RESTRICT",
        ),
        Index("ix_document_versions_document_created", "document_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String)
    original_filename: Mapped[str | None] = mapped_column(String)
    mime_type: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    file_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'UPLOADING'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentGrant(Base):
    __tablename__ = "document_grants"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document_grants"),
        ForeignKeyConstraint(
            ["document_id"],
            ["document.documents.id"],
            name="fk_document_grants_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)",
            name="ck_document_grants_revocation_pair",
        ),
        Index(
            "uq_document_grants_active_document_classroom",
            "document_id",
            "classroom_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_document_grants_active_classroom",
            "classroom_id",
            "document_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    classroom_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    granted_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency_key"),
        PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED')",
            name="ck_ingestion_jobs_status",
        ),
        CheckConstraint("attempt_number >= 0", name="ck_ingestion_jobs_attempt_nonnegative"),
        CheckConstraint(
            "(lease_until IS NULL AND lease_token IS NULL) OR "
            "(lease_until IS NOT NULL AND lease_token IS NOT NULL)",
            name="ck_ingestion_jobs_lease_pair",
        ),
        ForeignKeyConstraint(
            ["version_id"],
            ["document.document_versions.id"],
            name="fk_ingestion_jobs_version",
            ondelete="RESTRICT",
        ),
        Index("ix_ingestion_jobs_version_attempt", "version_id", "attempt_number"),
        Index("ix_ingestion_jobs_status_next_action", "status", "next_action_at"),
        Index("ix_ingestion_jobs_ai_job_id", "ai_job_id"),
        Index(
            "uq_ingestion_jobs_active_version",
            "version_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'PROCESSING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ai_job_id: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'PENDING'"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    index_ref: Mapped[str | None] = mapped_column(String)
    next_action_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    error_code: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
