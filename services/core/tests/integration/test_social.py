import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.audit import AuditEvent
from app.common.auth_dependencies import CurrentUser
from app.common.config import settings
from app.common.errors import AppError
from app.common.outbox import OutboxEvent
from app.common.pagination import Pagination
from app.modules.classroom.models import ClassMembership, EnrollmentMode, MembershipStatus
from app.modules.classroom.schemas import ClassCreateRequest, CourseCreateRequest
from app.modules.classroom.service import ClassroomService
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.social.calendar.models import CalendarEvent
from app.modules.social.calendar.schemas import (
    CalendarEventCreateRequest,
    CalendarEventUpdateRequest,
)
from app.modules.social.calendar.service import CalendarService, upsert_learning_deadline
from app.modules.social.comments.schemas import CommentCreateRequest
from app.modules.social.comments.service import CommentsService
from app.modules.social.feed.schemas import PostCreateRequest, PostUpdateRequest
from app.modules.social.feed.service import FeedService


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
def social(engine):
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        school_id = uuid4()

        def account(role: Role, *, account_school=school_id):
            user_id = uuid4()
            user = User(
                id=user_id,
                email=None if role == Role.STUDENT else f"{user_id}@example.com",
                username=f"student.{user_id.hex}" if role == Role.STUDENT else None,
                display_name=f"{role.value} {user_id.hex[:5]}",
                school_id=account_school,
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
                school_id=account_school,
            )

        users = {
            "admin": account(Role.ADMIN),
            "other_admin": account(Role.ADMIN, account_school=uuid4()),
            "teacher": account(Role.LECTURER),
            "student": account(Role.STUDENT),
            "student2": account(Role.STUDENT),
        }
        classroom = ClassroomService(session)
        course = classroom.create_course(
            users["admin"],
            CourseCreateRequest(code="SOC" + uuid4().hex[:8], name="Social integration"),
        )
        class_response = classroom.create_class(
            users["admin"],
            ClassCreateRequest(
                course_id=course.id,
                name="Social class",
                academic_year="2026-2027",
                semester="1",
                grade_level=9,
                enrollment_mode=EnrollmentMode.MANUAL,
                primary_lecturer_id=users["teacher"].id,
            ),
        )
        classroom.add_member(class_response.id, users["admin"], users["student"].id)
        classroom.add_member(class_response.id, users["admin"], users["student2"].id)
        yield session, classroom, class_response.id, users
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def test_feed_comments_permissions_outbox_audit_and_soft_delete(social):
    session, _classroom, class_id, users = social
    feed, comments = FeedService(session), CommentsService(session)

    post = feed.create_post(class_id, PostCreateRequest(body="hello"), users["student"])
    assert post.author.display_name is not None
    assert "email" not in post.author.model_dump()
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(post.id)))
    assert event.event_type == "SOCIAL_POST_CREATED"
    assert "body" not in event.payload_json

    comment = comments.create_comment(
        class_id,
        post.id,
        CommentCreateRequest(body="reply"),
        users["student2"],
    )
    comment_event = session.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == str(comment.id))
    )
    assert comment_event.event_type == "SOCIAL_COMMENT_CREATED"
    assert "body" not in comment_event.payload_json

    with pytest.raises(AppError) as hidden:
        feed.list_posts(class_id, Pagination(limit=20, cursor=None), users["admin"])
    assert hidden.value.status_code == 404
    with pytest.raises(AppError) as cross_school:
        feed.delete_post(class_id, post.id, users["other_admin"], uuid4())
    assert cross_school.value.status_code == 404

    feed.delete_post(class_id, post.id, users["admin"], uuid4())
    assert (
        feed.list_posts(class_id, Pagination(limit=20, cursor=None), users["student"]).items == []
    )
    assert (
        session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == post.id,
                AuditEvent.action == "MODERATE_DELETE_POST",
            )
        )
        is not None
    )
    with pytest.raises(AppError) as deleted_parent:
        comments.list_comments(
            class_id,
            post.id,
            Pagination(limit=20, cursor=None),
            users["student"],
        )
    assert deleted_parent.value.status_code == 404


def test_feed_stable_pagination_and_ended_author_loses_write(social):
    session, _classroom, class_id, users = social
    feed = FeedService(session)
    common_time = datetime.now(UTC)
    created_ids = []
    for index in range(27):
        post = feed.create_post(
            class_id,
            PostCreateRequest(body=f"post {index}"),
            users["student"],
        )
        model = feed.repository.get_post_by_id(post.id)
        model.created_at = common_time
        created_ids.append(post.id)
    session.commit()

    seen = []
    cursor = None
    while True:
        page = feed.list_posts(class_id, Pagination(limit=7, cursor=cursor), users["student"])
        seen.extend(item.id for item in page.items)
        if page.next_cursor is None:
            break
        from app.common.pagination import decode_cursor

        cursor = decode_cursor(page.next_cursor)
    assert len(seen) == len(set(seen)) == 27
    assert set(seen) == set(created_ids)

    membership = session.scalar(
        select(ClassMembership).where(
            ClassMembership.class_id == class_id,
            ClassMembership.student_id == users["student"].id,
            ClassMembership.status == MembershipStatus.ACTIVE,
        )
    )
    membership.status = MembershipStatus.ENDED
    membership.ended_at = datetime.now(UTC)
    session.commit()
    with pytest.raises(AppError) as denied:
        feed.update_post(
            class_id,
            created_ids[0],
            PostUpdateRequest(body="cannot edit"),
            users["student"],
        )
    assert denied.value.status_code == 404


def test_calendar_core_and_learning_versioning(social):
    session, classroom, class_id, users = social
    calendar = CalendarService(session)
    start = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(AppError) as student_denied:
        calendar.create_event(
            class_id,
            CalendarEventCreateRequest(
                title="Student event", starts_at=start, ends_at=start + timedelta(hours=1)
            ),
            users["student"],
        )
    assert student_denied.value.status_code == 403

    core_event = calendar.create_event(
        class_id,
        CalendarEventCreateRequest(
            title="Teacher event", starts_at=start, ends_at=start + timedelta(hours=1)
        ),
        users["teacher"],
    )
    with pytest.raises(AppError) as invalid_patch:
        calendar.update_event(
            class_id,
            core_event.id,
            CalendarEventUpdateRequest(starts_at=core_event.ends_at),
            users["teacher"],
        )
    assert invalid_patch.value.status_code == 422

    projected = upsert_learning_deadline(
        session,
        class_id=class_id,
        external_ref="assessment-1",
        title="Deadline",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        version=2,
    )
    unchanged = upsert_learning_deadline(
        session,
        class_id=class_id,
        external_ref="assessment-1",
        title="Stale",
        starts_at=start,
        ends_at=start + timedelta(hours=3),
        version=1,
    )
    assert unchanged.id == projected.id
    assert unchanged.title == "Deadline"
    assert session.scalars(
        select(CalendarEvent).where(CalendarEvent.external_ref == "assessment-1")
    ).all() == [projected]
    deadline_events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "CALENDAR_DEADLINE_CHANGED")
    ).all()
    assert len(deadline_events) == 1

    with pytest.raises(AppError) as read_only:
        calendar.delete_event(class_id, projected.id, users["teacher"])
    assert read_only.value.status_code == 400

    classroom.set_archived(class_id, users["admin"], archived=True)
    page = calendar.list_events(class_id, Pagination(limit=20, cursor=None), users["student"])
    assert len(page.items) == 2
    with pytest.raises(AppError) as archived:
        calendar.delete_event(class_id, core_event.id, users["teacher"])
    assert archived.value.status_code == 409
