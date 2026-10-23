"""Explicit offline School provisioning and dev fixture workflows."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.classroom.models import School


def maintenance_schools(*, session: Session) -> list[dict]:
    return [
        {"school_id": str(row.id), "name": row.name}
        for row in session.scalars(select(School).order_by(School.id))
    ]


def maintenance_user_schools(*, session: Session) -> dict[str, list[str]]:
    """Report historical bindings for review; never infer or assign a School."""
    from app.modules.classroom.models import (
        ClassMembership,
        HomeroomClass,
        HomeroomRoster,
        SubjectClass,
        TeachingAssignment,
    )

    queries = [
        select(ClassMembership.student_id, SubjectClass.school_id).join(
            SubjectClass, SubjectClass.id == ClassMembership.class_id
        ),
        select(TeachingAssignment.lecturer_id, SubjectClass.school_id).join(
            SubjectClass, SubjectClass.id == TeachingAssignment.class_id
        ),
        select(HomeroomRoster.student_id, HomeroomClass.school_id).join(
            HomeroomClass, HomeroomClass.id == HomeroomRoster.homeroom_class_id
        ),
    ]
    scopes = {}
    for query in queries:
        for user_id, school_id in session.execute(query):
            scopes.setdefault(str(user_id), set()).add(str(school_id))
    return {user_id: sorted(schools) for user_id, schools in scopes.items()}


def maintenance_provision_schools(schools: dict[UUID, str], *, session: Session) -> None:
    for school_id, name in sorted(schools.items()):
        if not name.strip() or len(name) > 200:
            raise ValueError("School name must contain 1–200 characters")
        school = session.get(School, school_id)
        if school is None:
            session.add(School(id=school_id, name=name))
        elif school.name not in (None, name):
            raise ValueError("School name mismatch; review explicit mapping")
        elif school.name is None:
            school.name = name
    session.flush()


def seed_dev_classroom(*, identities: dict, session: Session) -> None:
    from app.modules.classroom.schemas import (
        ClassCreateRequest,
        CourseCreateRequest,
        HomeroomCreateRequest,
        TeachingAssignmentsRequest,
    )
    from app.modules.classroom.service import ClassroomService
    from app.modules.identity.public import admin_actor

    actor = admin_actor(identities["admin_id"], session=session)
    service = ClassroomService(session, correlation_id=uuid4(), reason_code="ADMIN_INTERVENTION")
    course = service.create_course(
        actor, CourseCreateRequest(code="SEED-MATH", name="Seed Mathematics"), commit=False
    )
    for grade in range(6, 13):
        room = service.create_homeroom(
            actor,
            HomeroomCreateRequest(
                name=f"Seed {grade}A", academic_year="2026-2027", grade_level=grade
            ),
            commit=False,
        )
        if grade == 9:
            service.set_roster(actor, room.id, identities["student_ids"][:2], commit=False)
        for mode in ("AUTO", "MANUAL"):
            klass = service.create_class(
                actor,
                ClassCreateRequest(
                    course_id=course.id,
                    name=f"Seed Math {grade} {mode}",
                    academic_year="2026-2027",
                    semester="1",
                    grade_level=grade,
                    homeroom_class_id=room.id,
                    enrollment_mode=mode,
                    primary_lecturer_id=identities["lecturer_ids"][0],
                ),
                commit=False,
            )
            service.set_teachers(
                klass.id,
                actor,
                TeachingAssignmentsRequest(
                    primary_lecturer_id=identities["lecturer_ids"][0],
                    assisting_lecturer_ids=[identities["lecturer_ids"][1]],
                ),
                commit=False,
            )
            if mode == "MANUAL" and grade == 9:
                service.add_member(klass.id, actor, identities["student_ids"][0], commit=False)
