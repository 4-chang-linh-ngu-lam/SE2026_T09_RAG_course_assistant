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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class ClassStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EnrollmentMode(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class TeachingRole(StrEnum):
    PRIMARY = "PRIMARY"
    ASSISTING = "ASSISTING"


class School(Base):
    __tablename__ = "schools"

    name: Mapped[str | None] = mapped_column(String(200))


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (UniqueConstraint("school_id", "label", name="uq_academic_year_school_label"),)

    school_id: Mapped[UUID] = mapped_column(ForeignKey("core.schools.id"), index=True)
    label: Mapped[str] = mapped_column(String(30))


class Semester(Base):
    __tablename__ = "semesters"
    __table_args__ = (UniqueConstraint("academic_year_id", "name", name="uq_semester_year_name"),)

    academic_year_id: Mapped[UUID] = mapped_column(ForeignKey("core.academic_years.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_course_school_code"),
        CheckConstraint("code <> ''", name="ck_courses_code_not_empty"),
    )

    school_id: Mapped[UUID] = mapped_column(ForeignKey("core.schools.id"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))


class HomeroomClass(Base):
    __tablename__ = "homeroom_classes"
    __table_args__ = (
        UniqueConstraint("school_id", "academic_year_id", "name", name="uq_homeroom_year_name"),
        CheckConstraint("grade_level BETWEEN 6 AND 12", name="ck_homeroom_grade_level"),
        CheckConstraint("roster_version >= 1", name="ck_homeroom_roster_version"),
    )

    school_id: Mapped[UUID] = mapped_column(ForeignKey("core.schools.id"), index=True)
    academic_year_id: Mapped[UUID] = mapped_column(ForeignKey("core.academic_years.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    grade_level: Mapped[int]
    roster_version: Mapped[int] = mapped_column(default=1, server_default=text("1"))


class HomeroomRoster(Base):
    __tablename__ = "homeroom_rosters"
    __table_args__ = (
        Index(
            "uq_active_homeroom_student",
            "homeroom_class_id",
            "student_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    homeroom_class_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.homeroom_classes.id"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubjectClass(Base):
    __tablename__ = "subject_classes"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "academic_year_id",
            "semester_id",
            "course_id",
            "name",
            name="uq_subject_class_identity",
        ),
        CheckConstraint("grade_level BETWEEN 6 AND 12", name="ck_subject_grade_level"),
        CheckConstraint("version >= 1", name="ck_subject_version"),
    )

    school_id: Mapped[UUID] = mapped_column(ForeignKey("core.schools.id"), index=True)
    academic_year_id: Mapped[UUID] = mapped_column(ForeignKey("core.academic_years.id"), index=True)
    semester_id: Mapped[UUID] = mapped_column(ForeignKey("core.semesters.id"), index=True)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("core.courses.id"), index=True)
    homeroom_class_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("core.homeroom_classes.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    grade_level: Mapped[int]
    enrollment_mode: Mapped[EnrollmentMode] = mapped_column(
        Enum(EnrollmentMode, native_enum=False, create_constraint=True, name="enrollment_mode")
    )
    status: Mapped[ClassStatus] = mapped_column(
        Enum(ClassStatus, native_enum=False, create_constraint=True, name="class_status"),
        default=ClassStatus.ACTIVE,
        server_default=ClassStatus.ACTIVE.value,
    )
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))


class TeachingAssignment(Base):
    __tablename__ = "teaching_assignments"
    __table_args__ = (
        Index(
            "uq_active_teacher_per_class",
            "class_id",
            "lecturer_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index(
            "uq_active_primary_teacher",
            "class_id",
            unique=True,
            postgresql_where=text("role = 'PRIMARY' AND ended_at IS NULL"),
        ),
    )

    class_id: Mapped[UUID] = mapped_column(ForeignKey("core.subject_classes.id"), index=True)
    lecturer_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id"), index=True)
    role: Mapped[TeachingRole] = mapped_column(
        Enum(TeachingRole, native_enum=False, create_constraint=True, name="teaching_role")
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassMembership(Base):
    __tablename__ = "class_memberships"
    __table_args__ = (
        Index(
            "uq_active_class_membership",
            "class_id",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    class_id: Mapped[UUID] = mapped_column(ForeignKey("core.subject_classes.id"), index=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id"), index=True)
    source: Mapped[EnrollmentMode] = mapped_column(
        Enum(EnrollmentMode, native_enum=False, create_constraint=True, name="membership_source")
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, create_constraint=True, name="membership_status")
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
