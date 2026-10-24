from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Document(Base):
    __tablename__ = "documents"
    school_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    owner_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(8))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    serving_version: Mapped[int | None] = mapped_column(Integer)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("revision > 0"),)


class Version(Base):
    __tablename__ = "document_versions"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.documents.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Written once on successful publish, never returned from a non-READY version.
    content: Mapped[list | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("document_id", "number"),
        CheckConstraint("number > 0 AND size > 0 AND generation >= 0"),
        CheckConstraint("status IN ('PENDING','PROCESSING','READY','FAILED')"),
    )


class Grant(Base):
    __tablename__ = "class_document_grants"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.documents.id"), index=True)
    class_id: Mapped[UUID] = mapped_column(index=True)
    school_id: Mapped[UUID]
    granted_by: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("document_id", "class_id"), CheckConstraint("revision > 0"))


class Note(Base):
    __tablename__ = "source_notes"
    user_id: Mapped[UUID] = mapped_column(index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    class_id: Mapped[UUID] = mapped_column(index=True)
    document_title: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(200))
    locator_id: Mapped[str] = mapped_column(String(16))
    note_text: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    client_request_id: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "client_request_id"),)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    user_id: Mapped[UUID] = mapped_column(index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    class_id: Mapped[UUID]
    document_title: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(200))
    locator_id: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", "class_id", "version", "locator_id"),
    )


class UploadReceipt(Base):
    __tablename__ = "upload_receipts"
    user_id: Mapped[UUID]
    request_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)


class Outbox(Base):
    __tablename__ = "outbox"
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, index=True)
    envelope: Mapped[dict] = mapped_column(JSONB)
    notification_payload: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


Index("ix_document_grant_active", Grant.class_id, Grant.active)
