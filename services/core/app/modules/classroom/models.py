from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class ClassStatus(StrEnum):
    """Lifecycle of a class; ARCHIVED is read-only (Rule F5)."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ClassRole(StrEnum):
    OWNER = "OWNER"
    CO_LECTURER = "CO_LECTURER"
    STUDENT = "STUDENT"


class MembershipStatus(StrEnum):
    """Row history model: LEFT/REMOVED rows are kept; re-admission flips back to ACTIVE.

    REMOVED = expelled by a lecturer (needs re-admission to return);
    LEFT = self-departure (may rejoin via join code).
    """

    ACTIVE = "ACTIVE"
    LEFT = "LEFT"
    REMOVED = "REMOVED"


class JoinRequestStatus(StrEnum):
    """One PENDING per (class, student) enforced by a partial unique index."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CoLecturerInvitationStatus(StrEnum):
    """PENDING expires after 7 days; re-inviting retires expired PENDING rows."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Course(Base):
    """Course catalog entry; classes belong to exactly one course."""

    __tablename__ = "courses"
    __table_args__ = (CheckConstraint("code <> ''", name="ck_courses_code_not_empty"),)

    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)


class Class(Base):
    """A teaching class; join codes are stored hashed, shown once at creation."""

    __tablename__ = "classes"
    __table_args__ = (
        CheckConstraint("name <> ''", name="ck_classes_name_not_empty"),
        CheckConstraint("join_code_hash <> ''", name="ck_classes_join_code_hash_not_empty"),
    )

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.courses.id", ondelete="RESTRICT"), index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    join_code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    join_enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    status: Mapped[ClassStatus] = mapped_column(
        Enum(ClassStatus, native_enum=False, create_constraint=True, name="class_status"),
        default=ClassStatus.ACTIVE,
        server_default=ClassStatus.ACTIVE.value,
    )


class ClassMembership(Base):
    """User-in-class state; the partial unique index allows one ACTIVE row per pair."""

    __tablename__ = "class_memberships"
    __table_args__ = (
        Index(
            "ix_core_class_memberships_active",
            "class_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.classes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    class_role: Mapped[ClassRole] = mapped_column(
        Enum(ClassRole, native_enum=False, create_constraint=True, name="class_role")
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, create_constraint=True, name="membership_status")
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JoinRequest(Base):
    """Student's ask to join; decisions are immutable once left PENDING."""

    __tablename__ = "join_requests"
    __table_args__ = (
        Index(
            "ix_core_join_requests_pending",
            "class_id",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.classes.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[JoinRequestStatus] = mapped_column(
        Enum(
            JoinRequestStatus, native_enum=False, create_constraint=True, name="join_request_status"
        ),
        default=JoinRequestStatus.PENDING,
        server_default=JoinRequestStatus.PENDING.value,
    )
    decided_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoLecturerInvitation(Base):
    """Owner's ask for a lecturer to co-teach; an accepted invite creates or upgrades membership."""

    __tablename__ = "co_lecturer_invitations"
    __table_args__ = (
        Index(
            "ix_core_co_lecturer_invitations_pending",
            "class_id",
            "lecturer_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.classes.id", ondelete="CASCADE"), index=True
    )
    lecturer_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[CoLecturerInvitationStatus] = mapped_column(
        Enum(
            CoLecturerInvitationStatus,
            native_enum=False,
            create_constraint=True,
            name="co_lecturer_invitation_status",
        ),
        default=CoLecturerInvitationStatus.PENDING,
        server_default=CoLecturerInvitationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
