from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class Role(StrEnum):
    STUDENT = "STUDENT"
    LECTURER = "LECTURER"
    ADMIN = "ADMIN"


class TokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"
    ADMIN_INVITATION = "ADMIN_INVITATION"
    STUDENT_ACTIVATION = "STUDENT_ACTIVATION"
    STUDENT_PASSWORD_RESET = "STUDENT_PASSWORD_RESET"


class DataRequestType(StrEnum):
    ACCESS = "ACCESS"
    EXPORT = "EXPORT"
    CORRECTION = "CORRECTION"
    DELETE = "DELETE"


class DataRequestStatus(StrEnum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        CheckConstraint("username = lower(username)", name="ck_users_username_lowercase"),
        CheckConstraint("session_version >= 1", name="ck_users_session_version"),
    )

    email: Mapped[str | None] = mapped_column(String(320))
    username: Mapped[str | None] = mapped_column(String(200))
    school_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("core.schools.id", name="fk_users_school_id_schools"), index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, create_constraint=True, name="user_status"),
        default=UserStatus.PENDING_VERIFICATION,
        server_default=UserStatus.PENDING_VERIFICATION.value,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(default=1, server_default=text("1"))


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_role_assignments_user_role"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, create_constraint=True, name="system_role")
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), index=True
    )
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OneTimeToken(Base):
    __tablename__ = "one_time_tokens"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(TokenPurpose, native_enum=False, create_constraint=True, name="token_purpose")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CredentialDelivery(Base):
    """Retry state for email tokens; the raw token is always derived in memory."""

    __tablename__ = "credential_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','DELIVERED','CANCELLED','NEEDS_REISSUE')",
            name="ck_credential_delivery_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_credential_delivery_attempts"),
        UniqueConstraint("token_id", name="uq_credential_delivery_token"),
        Index("idx_credential_delivery_pending", "status", "available_at"),
    )

    token_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.one_time_tokens.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="PENDING", server_default="PENDING", nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class DataRequest(Base):
    __tablename__ = "data_requests"
    __table_args__ = (Index("ix_core_data_requests_user_id_id", "user_id", "id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id"))
    request_type: Mapped[DataRequestType] = mapped_column(
        Enum(DataRequestType, native_enum=False, create_constraint=True, name="data_request_type")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DataRequestStatus] = mapped_column(
        Enum(
            DataRequestStatus, native_enum=False, create_constraint=True, name="data_request_status"
        ),
        default=DataRequestStatus.PENDING,
        server_default=DataRequestStatus.PENDING.value,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
