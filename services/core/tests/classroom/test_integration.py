import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.config import settings
from app.common.errors import AppError
from app.common.outbox import OutboxEvent
from app.modules.classroom.models import (
    ClassMembership,
    EnrollmentMode,
    MembershipStatus,
    TeachingRole,
)
from app.modules.classroom.public import check_class_action
from app.modules.classroom.schemas import (
    ClassAccessAction,
    ClassCreateRequest,
    CourseCreateRequest,
    EnrollmentModeRequest,
    HomeroomCreateRequest,
    TeachingAssignmentsRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus


@pytest.fixture(scope="module")
def engine():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    core_dir = Path(__file__).resolve().parents[2]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "migrations"))
    previous = settings.database_url
    settings.database_url = database_url
    try:
        command.upgrade(config, "head")
        command.check(config)
    finally:
        settings.database_url = previous
    test_engine = create_engine(database_url, hide_parameters=True)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def classroom(engine):
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:

        def account(role: Role, school_id):
            user_id = uuid4()
            user = User(
                id=user_id,
                email=f"{user_id}@example.com" if role != Role.STUDENT else None,
                username=f"student.{user_id.hex}" if role == Role.STUDENT else None,
                school_id=school_id,
                password_hash="test-only-hash",
                status=UserStatus.ACTIVE,
                email_verified_at=datetime.now(UTC) if role != Role.STUDENT else None,
                activated_at=datetime.now(UTC) if role == Role.STUDENT else None,
            )
            session.add(user)
            session.flush()
            session.add(RoleAssignment(user_id=user_id, role=role))
            session.flush()
            return CurrentUser(
                id=user_id,
                status="ACTIVE",
                session_version=1,
                roles=[role.value],
                school_id=school_id,
            )

        school_id = uuid4()
        users = {
            "admin": account(Role.ADMIN, school_id),
            "other_admin": account(Role.ADMIN, uuid4()),
            "teacher": account(Role.LECTURER, school_id),
            "teacher2": account(Role.LECTURER, school_id),
            "student": account(Role.STUDENT, school_id),
            "student2": account(Role.STUDENT, school_id),
        }
        yield session, ClassroomService(session), users
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def _class(service, admin, course_id, teacher_id, homeroom_id, *, mode):
    return service.create_class(
        admin,
        ClassCreateRequest(
            course_id=course_id,
            name="Toán " + uuid4().hex[:8],
            academic_year="2026-2027",
            semester="1",
            grade_level=9,
            homeroom_class_id=homeroom_id,
            enrollment_mode=mode,
            primary_lecturer_id=teacher_id,
        ),
    )


def _setup(service, users):
    admin = users["admin"]
    course = service.create_course(
        admin, CourseCreateRequest(code="MATH" + uuid4().hex[:8], name="Toán")
    )
    homeroom = service.create_homeroom(
        admin,
        HomeroomCreateRequest(
            name="9A" + uuid4().hex[:8], academic_year="2026-2027", grade_level=9
        ),
    )
    return course, homeroom


def test_admin_only_assignments_manual_transfer_and_archive(classroom):
    session, service, users = classroom
    admin, student = users["admin"], users["student"]
    course, homeroom = _setup(service, users)
    body = ClassCreateRequest(
        course_id=course.id,
        name="Không cho giáo viên tạo",
        academic_year="2026-2027",
        semester="1",
        grade_level=9,
        enrollment_mode=EnrollmentMode.MANUAL,
        primary_lecturer_id=users["teacher"].id,
    )
    with pytest.raises(AppError) as denied:
        service.create_class(users["teacher"], body)
    assert denied.value.status_code == 403

    first = _class(
        service, admin, course.id, users["teacher"].id, homeroom.id, mode=EnrollmentMode.MANUAL
    )
    second = _class(
        service, admin, course.id, users["teacher"].id, homeroom.id, mode=EnrollmentMode.MANUAL
    )
    member = service.add_member(first.id, admin, student.id)
    assert member.status == MembershipStatus.ACTIVE
    assert service.add_member(first.id, admin, student.id).id == member.id
    moved = service.transfer(first.id, second.id, student.id, admin)
    assert moved.status == MembershipStatus.ACTIVE
    assert not check_class_action(
        first.id, student.id, ClassAccessAction.PARTICIPATE_CURRENT_CLASS, session=session
    ).allowed
    assert check_class_action(
        first.id, student.id, ClassAccessAction.READ_OWN_HISTORY, session=session
    ).allowed
    assert check_class_action(
        first.id, users["teacher"].id, ClassAccessAction.GRADE_SUBMITTED_WORK, session=session
    ).allowed

    assignments = service.set_teachers(
        first.id,
        admin,
        TeachingAssignmentsRequest(primary_lecturer_id=users["teacher2"].id),
    )
    assert len(assignments) == 1 and assignments[0].role == TeachingRole.PRIMARY
    assert not check_class_action(
        first.id, users["teacher"].id, ClassAccessAction.GRADE_SUBMITTED_WORK, session=session
    ).allowed
    assert check_class_action(
        first.id, users["teacher2"].id, ClassAccessAction.GRADE_SUBMITTED_WORK, session=session
    ).allowed
    service.set_archived(second.id, admin, archived=True)
    assert check_class_action(
        second.id, student.id, ClassAccessAction.READ_CLASS_CONTENT, session=session
    ).allowed
    assert not check_class_action(
        second.id, student.id, ClassAccessAction.USE_AI_TUTOR, session=session
    ).allowed
    with pytest.raises(AppError) as denied:
        service.add_member(second.id, admin, users["student2"].id)
    assert denied.value.status_code == 409
    service.set_archived(second.id, admin, archived=False)
    with pytest.raises(AppError) as denied:
        service.set_archived(first.id, users["other_admin"], archived=True)
    assert denied.value.status_code == 404
    assert session.scalar(select(OutboxEvent.id).limit(1)) is not None


def test_auto_roster_transfer_preview_and_history(classroom):
    session, service, users = classroom
    admin, student, student2 = users["admin"], users["student"], users["student2"]
    course, first_home = _setup(service, users)
    second_home = service.create_homeroom(
        admin,
        HomeroomCreateRequest(
            name="9B" + uuid4().hex[:8], academic_year="2026-2027", grade_level=9
        ),
    )
    service.set_roster(admin, first_home.id, [student.id])
    first = _class(
        service, admin, course.id, users["teacher"].id, first_home.id, mode=EnrollmentMode.AUTO
    )
    second = _class(
        service, admin, course.id, users["teacher"].id, second_home.id, mode=EnrollmentMode.AUTO
    )
    assert check_class_action(
        first.id, student.id, ClassAccessAction.USE_AI_TUTOR, session=session
    ).allowed
    service.transfer_homeroom_student(first_home.id, second_home.id, student.id, admin)
    assert not check_class_action(
        first.id, student.id, ClassAccessAction.USE_AI_TUTOR, session=session
    ).allowed
    assert check_class_action(
        first.id, student.id, ClassAccessAction.READ_OWN_HISTORY, session=session
    ).allowed
    assert check_class_action(
        second.id, student.id, ClassAccessAction.USE_AI_TUTOR, session=session
    ).allowed

    manual = _class(
        service,
        admin,
        course.id,
        users["teacher"].id,
        second_home.id,
        mode=EnrollmentMode.MANUAL,
    )
    service.add_member(manual.id, admin, student2.id)
    preview = service.preview_auto(manual.id, admin)
    assert preview.add_student_ids == [student.id]
    assert preview.end_student_ids == [student2.id]
    service.set_roster(admin, second_home.id, [student.id, student2.id])
    with pytest.raises(AppError) as stale:
        service.set_enrollment_mode(
            manual.id,
            admin,
            EnrollmentModeRequest(
                mode=EnrollmentMode.AUTO,
                expected_class_version=preview.class_version,
                expected_roster_version=preview.roster_version,
            ),
        )
    assert stale.value.status_code == 409
    preview = service.preview_auto(manual.id, admin)
    service.set_enrollment_mode(
        manual.id,
        admin,
        EnrollmentModeRequest(
            mode=EnrollmentMode.AUTO,
            expected_class_version=preview.class_version,
            expected_roster_version=preview.roster_version,
        ),
    )
    service.set_roster(admin, second_home.id, [student.id])
    assert not check_class_action(
        manual.id, student2.id, ClassAccessAction.PARTICIPATE_CURRENT_CLASS, session=session
    ).allowed
    assert check_class_action(
        manual.id, student2.id, ClassAccessAction.READ_OWN_HISTORY, session=session
    ).allowed
    history = list(
        session.scalars(
            select(ClassMembership).where(
                ClassMembership.class_id == manual.id,
                ClassMembership.student_id == student2.id,
            )
        )
    )
    assert len(history) == 1 and history[0].status == MembershipStatus.ENDED
