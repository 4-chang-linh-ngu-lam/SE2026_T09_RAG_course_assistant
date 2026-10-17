from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.classroom.models import (
    AcademicYear,
    ClassMembership,
    ClassStatus,
    Course,
    EnrollmentMode,
    HomeroomClass,
    HomeroomRoster,
    MembershipStatus,
    School,
    Semester,
    SubjectClass,
    TeachingAssignment,
)


class ClassroomRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_school(self, school_id: UUID) -> None:
        # Identity school IDs are preassigned; this creates only their Classroom-owned row.
        self.session.execute(
            insert(School).values(id=school_id).on_conflict_do_nothing(index_elements=[School.id])
        )

    def ensure_academic_year(self, school_id: UUID, label: str) -> AcademicYear:
        self.session.execute(
            insert(AcademicYear)
            .values(school_id=school_id, label=label)
            .on_conflict_do_nothing(index_elements=[AcademicYear.school_id, AcademicYear.label])
        )
        return self.session.scalar(
            select(AcademicYear).where(
                AcademicYear.school_id == school_id, AcademicYear.label == label
            )
        )

    def ensure_semester(self, academic_year_id: UUID, name: str) -> Semester:
        self.session.execute(
            insert(Semester)
            .values(academic_year_id=academic_year_id, name=name)
            .on_conflict_do_nothing(index_elements=[Semester.academic_year_id, Semester.name])
        )
        return self.session.scalar(
            select(Semester).where(
                Semester.academic_year_id == academic_year_id, Semester.name == name
            )
        )

    def get_course(self, course_id: UUID) -> Course | None:
        return self.session.get(Course, course_id)

    def get_course_by_code(self, school_id: UUID, code: str) -> Course | None:
        return self.session.scalar(
            select(Course).where(Course.school_id == school_id, Course.code == code)
        )

    def get_homeroom(self, homeroom_id: UUID, *, for_update: bool = False) -> HomeroomClass | None:
        query = select(HomeroomClass).where(HomeroomClass.id == homeroom_id)
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def get_homeroom_by_name(
        self, school_id: UUID, academic_year_id: UUID, name: str
    ) -> HomeroomClass | None:
        return self.session.scalar(
            select(HomeroomClass).where(
                HomeroomClass.school_id == school_id,
                HomeroomClass.academic_year_id == academic_year_id,
                HomeroomClass.name == name,
            )
        )

    def active_roster(self, homeroom_id: UUID) -> list[HomeroomRoster]:
        return list(
            self.session.scalars(
                select(HomeroomRoster).where(
                    HomeroomRoster.homeroom_class_id == homeroom_id,
                    HomeroomRoster.ended_at.is_(None),
                )
            )
        )

    def auto_classes_for_homeroom(self, homeroom_id: UUID) -> list[SubjectClass]:
        return list(
            self.session.scalars(
                select(SubjectClass)
                .where(
                    SubjectClass.homeroom_class_id == homeroom_id,
                    SubjectClass.enrollment_mode == EnrollmentMode.AUTO,
                    SubjectClass.status == ClassStatus.ACTIVE,
                )
                .order_by(SubjectClass.id)
                .with_for_update()
            )
        )

    def get_class(self, class_id: UUID, *, for_update: bool = False) -> SubjectClass | None:
        query = select(SubjectClass).where(SubjectClass.id == class_id)
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def list_classes(
        self, school_id: UUID, user_id: UUID, *, is_admin: bool, limit: int, cursor: UUID | None
    ) -> list[SubjectClass]:
        query = select(SubjectClass).where(SubjectClass.school_id == school_id)
        if not is_admin:
            enrolled = exists(
                select(ClassMembership.id).where(
                    ClassMembership.class_id == SubjectClass.id,
                    ClassMembership.student_id == user_id,
                    ClassMembership.status == MembershipStatus.ACTIVE,
                )
            )
            assigned = exists(
                select(TeachingAssignment.id).where(
                    TeachingAssignment.class_id == SubjectClass.id,
                    TeachingAssignment.lecturer_id == user_id,
                    TeachingAssignment.ended_at.is_(None),
                )
            )
            query = query.where(or_(enrolled, assigned))
        if cursor is not None:
            query = query.where(SubjectClass.id > cursor)
        return list(self.session.scalars(query.order_by(SubjectClass.id).limit(limit + 1)))

    def active_memberships(self, class_id: UUID) -> list[ClassMembership]:
        return list(
            self.session.scalars(
                select(ClassMembership).where(
                    ClassMembership.class_id == class_id,
                    ClassMembership.status == MembershipStatus.ACTIVE,
                )
            )
        )

    def active_membership(self, class_id: UUID, student_id: UUID) -> ClassMembership | None:
        return self.session.scalar(
            select(ClassMembership).where(
                ClassMembership.class_id == class_id,
                ClassMembership.student_id == student_id,
                ClassMembership.status == MembershipStatus.ACTIVE,
            )
        )

    def has_membership_history(self, class_id: UUID, student_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(ClassMembership.id)
                .where(
                    ClassMembership.class_id == class_id,
                    ClassMembership.student_id == student_id,
                )
                .limit(1)
            )
            is not None
        )

    def active_teachers(self, class_id: UUID) -> list[TeachingAssignment]:
        return list(
            self.session.scalars(
                select(TeachingAssignment).where(
                    TeachingAssignment.class_id == class_id,
                    TeachingAssignment.ended_at.is_(None),
                )
            )
        )

    def active_teacher(self, class_id: UUID, lecturer_id: UUID) -> TeachingAssignment | None:
        return self.session.scalar(
            select(TeachingAssignment).where(
                TeachingAssignment.class_id == class_id,
                TeachingAssignment.lecturer_id == lecturer_id,
                TeachingAssignment.ended_at.is_(None),
            )
        )

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row
