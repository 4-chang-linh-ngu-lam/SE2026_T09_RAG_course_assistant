import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.bootstrap import register_routers
from app.common.audit import AuditEvent
from app.common.auth_dependencies import CurrentUser
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.common.outbox import OutboxEvent
from app.common.pagination import encode_cursor
from app.common.security import create_access_token
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


@pytest.fixture
def classroom_http(classroom, monkeypatch):
    session, service, users = classroom
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(settings, "secret_key", SecretStr(secrets.token_urlsafe(48)))

    def headers(actor="admin"):
        user = users[actor]
        return {
            "Authorization": "Bearer "
            + create_access_token(user.id, user.roles, user.session_version)
        }

    with TestClient(app, base_url="https://testserver") as client:
        yield client, headers, session, service, users


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


def _read_urls(service, users):
    course, homeroom = _setup(service, users)
    klass = _class(
        service,
        users["admin"],
        course.id,
        users["teacher"].id,
        homeroom.id,
        mode=EnrollmentMode.MANUAL,
    )
    return (
        "/api/v1/admin/courses",
        "/api/v1/admin/academic-years",
        f"/api/v1/admin/academic-years/{homeroom.academic_year_id}/semesters",
        "/api/v1/admin/homeroom-classes",
        f"/api/v1/admin/homeroom-classes/{homeroom.id}/roster",
        f"/api/v1/admin/classes/{klass.id}/teaching-assignments",
    )


@pytest.mark.parametrize("actor", ["teacher", "student"])
def test_admin_reads_require_current_admin_and_do_not_write(classroom_http, actor):
    client, headers, session, service, users = classroom_http
    urls = _read_urls(service, users)
    before = (
        session.scalar(select(func.count()).select_from(AuditEvent)),
        session.scalar(select(func.count()).select_from(OutboxEvent)),
    )
    correlation = str(uuid4())
    for url in urls:
        unauthenticated = client.get(url)
        assert unauthenticated.status_code == 401
        denied = client.get(url, headers=headers(actor))
        assert denied.status_code == 403
        assert denied.headers["Cache-Control"] == "no-store"
        allowed = client.get(url, headers={**headers(), "X-Correlation-ID": correlation})
        assert allowed.status_code == 200
        assert allowed.headers["Cache-Control"] == "no-store"
        assert allowed.headers["X-Correlation-ID"] == correlation
    assert before == (
        session.scalar(select(func.count()).select_from(AuditEvent)),
        session.scalar(select(func.count()).select_from(OutboxEvent)),
    )


@pytest.mark.parametrize("revocation", ["LOCKED", "ROLE_REMOVED", "SESSION_REVOKED"])
def test_admin_reads_recheck_current_database_actor(classroom_http, revocation):
    client, headers, session, service, users = classroom_http
    urls = _read_urls(service, users)
    issued_headers = headers()
    actor = session.get(User, users["admin"].id)
    if revocation == "LOCKED":
        actor.status = UserStatus.LOCKED
    elif revocation == "ROLE_REMOVED":
        assignment = session.scalar(
            select(RoleAssignment).where(RoleAssignment.user_id == actor.id)
        )
        session.delete(assignment)
    else:
        actor.session_version += 1
    session.flush()
    expected = 403 if revocation == "ROLE_REMOVED" else 401
    for url in urls:
        response = client.get(url, headers=issued_headers)
        assert response.status_code == expected
        assert response.headers["Cache-Control"] == "no-store"


def test_admin_read_resources_and_pagination_are_school_and_year_scoped(classroom_http):
    client, headers, _session, service, users = classroom_http
    urls = _read_urls(service, users)
    admin_headers = headers()
    other_admin = users["other_admin"]
    foreign_course = service.create_course(
        other_admin, CourseCreateRequest(code="OTHER", name="Other-school course")
    )
    foreign_home = service.create_homeroom(
        other_admin,
        HomeroomCreateRequest(name="Other school", academic_year="2026-2027", grade_level=9),
    )
    # A caller-supplied school selector cannot change server-owned scope.
    courses = client.get(
        urls[0], headers=admin_headers, params={"school_id": str(other_admin.school_id)}
    )
    assert courses.status_code == 200
    assert all(row["school_id"] == str(users["admin"].school_id) for row in courses.json()["items"])
    assert str(foreign_course.id) not in {row["id"] for row in courses.json()["items"]}
    for foreign_url in (
        f"/api/v1/admin/academic-years/{foreign_home.academic_year_id}/semesters",
        f"/api/v1/admin/homeroom-classes/{foreign_home.id}/roster",
        f"/api/v1/admin/classes/{uuid4()}/teaching-assignments",
    ):
        assert client.get(foreign_url, headers=admin_headers).status_code == 404
    for own_resource in (urls[2], urls[4], urls[5]):
        assert client.get(own_resource, headers=headers("other_admin")).status_code == 404
    for url, cursor in (
        (urls[0], foreign_course.id),
        (urls[1], foreign_home.academic_year_id),
        (urls[3], foreign_home.id),
        (urls[0], uuid4()),
    ):
        assert (
            client.get(
                url, headers=admin_headers, params={"cursor": encode_cursor(cursor)}
            ).status_code
            == 400
        )
    own_home = service.create_homeroom(
        users["admin"],
        HomeroomCreateRequest(name="Next year", academic_year="2027-2028", grade_level=9),
    )
    # Create the next year's semester through the existing repository setup
    # path, without adding a mutation endpoint.
    other_semester = service.repository.ensure_semester(own_home.academic_year_id, "2")
    assert (
        client.get(
            urls[2], headers=admin_headers, params={"cursor": encode_cursor(other_semester.id)}
        ).status_code
        == 400
    )


def test_admin_reads_use_current_school_instead_of_issued_jwt_scope(classroom_http):
    client, headers, session, service, users = classroom_http
    urls = _read_urls(service, users)
    issued_headers = headers()
    other_school = users["other_admin"].school_id
    foreign_course = service.create_course(
        users["other_admin"], CourseCreateRequest(code="OTHER", name="Current school")
    )
    actor = session.get(User, users["admin"].id)
    actor.school_id = other_school
    session.flush()
    response = client.get(urls[0], headers=issued_headers)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [str(foreign_course.id)]
    for old_resource in (urls[2], urls[4], urls[5]):
        assert client.get(old_resource, headers=issued_headers).status_code == 404


@pytest.mark.parametrize(
    "collection", ["courses", "academic-years", "homeroom-classes", "semesters"]
)
def test_admin_metadata_reads_paginate_every_item_once(classroom_http, collection):
    client, headers, session, service, users = classroom_http
    _read_urls(service, users)
    for index in range(3):
        service.create_course(
            users["admin"], CourseCreateRequest(code=f"PAGE{index}", name=f"Course {index}")
        )
        service.create_homeroom(
            users["admin"],
            HomeroomCreateRequest(
                name=f"Room {index}", academic_year=f"20{30 + index}-20{31 + index}", grade_level=9
            ),
        )
    url = f"/api/v1/admin/{collection}"
    if collection == "semesters":
        year = client.get("/api/v1/admin/academic-years", headers=headers()).json()["items"][0]
        for index in range(3):
            service.repository.ensure_semester(UUID(year["id"]), f"Semester {index}")
        session.flush()
        url = f"/api/v1/admin/academic-years/{year['id']}/semesters"
    all_rows = client.get(url, headers=headers()).json()["items"]
    assert len(all_rows) >= 3
    seen = []
    cursor = None
    while True:
        response = client.get(
            url, headers=headers(), params={"limit": 1, **({"cursor": cursor} if cursor else {})}
        )
        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) == 1
        seen.append(page["items"][0]["id"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(cursor) == 22 and "=" not in cursor
        assert len(seen) <= len(all_rows)
    assert seen == sorted(row["id"] for row in all_rows)
    assert len(seen) == len(set(seen))
    for limit in (0, 101):
        assert client.get(url, headers=headers(), params={"limit": limit}).status_code == 422
    assert client.get(url, headers=headers(), params={"cursor": "invalid"}).status_code == 400


def test_admin_roster_and_teacher_reads_show_current_state_only(classroom_http):
    client, headers, _session, service, users = classroom_http
    urls = _read_urls(service, users)
    homeroom_id = UUID(client.get(urls[3], headers=headers()).json()["items"][0]["id"])
    class_id = UUID(urls[5].split("/")[-2])
    roster = service.set_roster(users["admin"], homeroom_id, [users["student"].id])
    first = client.get(urls[4], headers=headers()).json()
    assert first == roster.model_dump(mode="json")
    roster = service.set_roster(users["admin"], homeroom_id, [users["student2"].id])
    second = client.get(urls[4], headers=headers()).json()
    assert second == roster.model_dump(mode="json")
    assert second["roster_version"] == first["roster_version"] + 1
    assert second["student_ids"] == [str(users["student2"].id)]
    initial = client.get(urls[5], headers=headers()).json()
    assert len(initial) == 1 and initial[0]["lecturer_id"] == str(users["teacher"].id)
    service.set_teachers(
        class_id,
        users["admin"],
        TeachingAssignmentsRequest(primary_lecturer_id=users["teacher2"].id),
    )
    current = client.get(urls[5], headers=headers()).json()
    assert len(current) == 1 and current[0]["lecturer_id"] == str(users["teacher2"].id)
    assert current[0]["role"] == "PRIMARY" and current[0]["ended_at"] is None
    service.set_archived(class_id, users["admin"], archived=True)
    assert client.get(urls[5], headers=headers()).json() == current


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
