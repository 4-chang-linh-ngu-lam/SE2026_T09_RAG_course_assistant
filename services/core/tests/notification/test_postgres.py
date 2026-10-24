"""Real PostgreSQL transactions, HTTP authorization and concurrent workers.

TEST_DATABASE_URL must identify a disposable test server/account with CREATEDB.
Every test uses a fresh sibling database and drops only that generated database.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.common.outbox import OutboxEvent, record_outbox_event
from app.common.pagination import Pagination
from app.common.security import create_access_token
from app.modules.classroom.models import ClassMembership, EnrollmentMode
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    CourseCreateRequest,
    EnrollmentModeRequest,
    HomeroomCreateRequest,
    TeachingAssignmentsRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.identity.public import get_current_user_snapshot
from app.modules.notification.models import Notification
from app.modules.notification.public import snapshot_audience
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.notification.worker import drain_outbox
from app.modules.social.calendar.service import upsert_learning_deadline
from app.modules.social.comments.schemas import CommentCreateRequest
from app.modules.social.comments.service import CommentsService
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.schemas import PostCreateRequest
from app.modules.social.feed.service import FeedService


@pytest.fixture
def database(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL server with CREATEDB")
    base_url = make_url(database_url)
    database_name = "notification_test_" + uuid4().hex
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    test_url = base_url.set(database=database_name)
    engine = create_engine(
        test_url, hide_parameters=True, connect_args={"options": "-c timezone=UTC"}
    )
    core_dir = Path(__file__).resolve().parents[2]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "migrations"))
    monkeypatch.setattr(settings, "database_url", test_url.render_as_string(hide_password=False))
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    try:
        command.upgrade(config, "head")
        command.check(config)
        yield SimpleNamespace(engine=engine, factory=factory, config=config)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def system(database):
    factory = database.factory
    with factory() as session:
        school_id = uuid4()
        users = {}
        for name, role in (
            ("admin", Role.ADMIN),
            ("teacher", Role.LECTURER),
            ("teacher2", Role.LECTURER),
            ("student", Role.STUDENT),
            ("student2", Role.STUDENT),
            ("late", Role.STUDENT),
            ("outsider", Role.STUDENT),
        ):
            user_id = uuid4()
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@example.com" if role != Role.STUDENT else None,
                    username=f"student.{user_id.hex}" if role == Role.STUDENT else None,
                    school_id=uuid4() if name == "outsider" else school_id,
                    display_name=name,
                    password_hash="test-only-not-a-credential",
                    status=UserStatus.ACTIVE,
                    activated_at=datetime.now(UTC) if role == Role.STUDENT else None,
                    email_verified_at=datetime.now(UTC) if role != Role.STUDENT else None,
                )
            )
            session.flush()
            session.add(RoleAssignment(user_id=user_id, role=role))
            session.flush()
            users[name] = get_current_user_snapshot(session, user_id)
        session.commit()
        classroom = ClassroomService(session)
        course = classroom.create_course(
            users["admin"], CourseCreateRequest(code="NOTIF", name="Notification tests")
        )
        klass = classroom.create_class(
            users["admin"],
            ClassCreateRequest(
                course_id=course.id,
                name="Class 9",
                academic_year="2026-2027",
                semester="1",
                grade_level=9,
                enrollment_mode=EnrollmentMode.MANUAL,
                primary_lecturer_id=users["teacher"].id,
            ),
        )
        classroom.add_member(klass.id, users["admin"], users["student"].id)
        classroom.add_member(klass.id, users["admin"], users["student2"].id)
        drain_outbox(session_factory=factory)
        session.execute(delete(Notification))
        session.execute(delete(OutboxEvent))
        session.commit()
        yield SimpleNamespace(
            **vars(database),
            session=session,
            classroom=classroom,
            class_id=klass.id,
            users=users,
            course_id=course.id,
        )


def _rows(system, recipient=None, event_type=None):
    with system.factory() as session:
        query = select(Notification).order_by(Notification.sequence)
        if recipient is not None:
            query = query.where(Notification.recipient_id == recipient)
        if event_type is not None:
            query = query.where(Notification.type == event_type)
        return list(session.scalars(query))


def _post(system):
    return FeedService(system.session).create_post(
        system.class_id, PostCreateRequest(body="Synthetic classroom post"), system.users["teacher"]
    )


def _version_event(system, version):
    event = record_outbox_event(
        system.session,
        event_type="CLASS_STATUS_CHANGED",
        aggregate_id=system.class_id,
        payload_json={
            "class_id": str(system.class_id),
            "version": version,
            "status": "ACTIVE",
            **snapshot_audience(system.session, system.class_id),
        },
    )
    system.session.commit()
    return event.id


def test_enrollment_producer_delivery_and_removed_student_snapshot(system):
    student = system.users["late"]
    system.classroom.add_member(system.class_id, system.users["admin"], student.id)
    event = system.session.scalar(select(OutboxEvent))
    assert str(student.id) in event.payload_json["recipient_ids"]
    system.session.rollback()
    assert drain_outbox(session_factory=system.factory) == 1
    assert len(_rows(system, student.id)) == 1
    system.classroom.end_member(system.class_id, system.users["admin"], student.id)
    assert drain_outbox(session_factory=system.factory) == 1
    assert len(_rows(system, student.id)) == 2


def test_auto_roster_sync_and_mode_change_produce_notifications(system):
    room = system.classroom.create_homeroom(
        system.users["admin"],
        HomeroomCreateRequest(name="AUTO 9A", grade_level=9, academic_year="2026-2027"),
    )
    klass = system.classroom.create_class(
        system.users["admin"],
        ClassCreateRequest(
            course_id=system.course_id,
            name="Auto classroom",
            academic_year="2026-2027",
            semester="1",
            grade_level=9,
            homeroom_class_id=room.id,
            enrollment_mode=EnrollmentMode.MANUAL,
            primary_lecturer_id=system.users["teacher"].id,
        ),
    )
    system.classroom.set_roster(system.users["admin"], room.id, [system.users["late"].id])
    preview = system.classroom.preview_auto(klass.id, system.users["admin"])
    system.classroom.set_enrollment_mode(
        klass.id,
        system.users["admin"],
        EnrollmentModeRequest(
            mode=EnrollmentMode.AUTO,
            expected_class_version=preview.class_version,
            expected_roster_version=preview.roster_version,
        ),
    )
    assert drain_outbox(session_factory=system.factory) == 2
    rows = _rows(system, system.users["late"].id)
    assert {row.type for row in rows} == {
        "CLASS_ENROLLMENT_CHANGED",
        "CLASS_ENROLLMENT_MODE_CHANGED",
    }
    system.classroom.set_roster(system.users["admin"], room.id, [])
    assert drain_outbox(session_factory=system.factory) == 1
    assert len(_rows(system, system.users["late"].id)) == 3


def test_producer_rollback_and_outbox_write_failure_are_atomic(system, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr("app.modules.classroom.service.record_outbox_event", fail)
    with pytest.raises(RuntimeError):
        system.classroom.add_member(system.class_id, system.users["admin"], system.users["late"].id)
    with system.factory() as db:
        assert (
            db.scalar(
                select(ClassMembership).where(ClassMembership.student_id == system.users["late"].id)
            )
            is None
        )
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    assert drain_outbox(session_factory=system.factory) == 0


def test_worker_never_observes_uncommitted_producer_event(system):
    _version_event(system, 10)
    with system.factory() as producer:
        event = record_outbox_event(
            producer,
            event_type="CLASS_STATUS_CHANGED",
            aggregate_id=system.class_id,
            payload_json={"class_id": str(system.class_id), "version": 11},
        )
        producer.flush()
        uncommitted_id = event.id
        assert drain_outbox(session_factory=system.factory) == 1
        producer.rollback()
    with system.factory() as db:
        assert db.get(OutboxEvent, uncommitted_id) is None
    assert {row.payload_json["version"] for row in _rows(system)} == {10}


def test_crash_after_insert_rolls_back_then_replay_dedups(system, monkeypatch):
    post = _post(system)

    class SimulatedCrash(BaseException):
        pass

    original = NotificationRepository.create

    def crash(self, **kwargs):
        original(self, **kwargs)
        raise SimulatedCrash

    monkeypatch.setattr(NotificationRepository, "create", crash)
    with pytest.raises(SimulatedCrash):
        drain_outbox(session_factory=system.factory)
    assert _rows(system) == []
    with system.factory() as db:
        assert db.get(ClassPost, post.id) is not None
        assert db.scalar(select(OutboxEvent)).published_at is None
    monkeypatch.setattr(NotificationRepository, "create", original)
    assert drain_outbox(session_factory=system.factory) == 1
    first_ids = {row.id for row in _rows(system)}
    with system.factory.begin() as db:
        db.execute(update(OutboxEvent).values(published_at=None))
    assert drain_outbox(session_factory=system.factory) == 1
    assert {row.id for row in _rows(system)} == first_ids
    assert len(first_ids) == 2


def test_retry_backoff_does_not_rollback_business_and_continues_after_poison(
    system, monkeypatch, caplog
):
    post = _post(system)
    original = NotificationRepository.create

    def fail(*args, **kwargs):
        raise RuntimeError("test-only-secret-should-never-be-logged")

    monkeypatch.setattr(NotificationRepository, "create", fail)
    assert drain_outbox(session_factory=system.factory) == 0
    with system.factory() as db:
        event = db.scalar(select(OutboxEvent))
        assert event.attempts == 1 and event.published_at is None
        assert event.available_at > db.scalar(select(func.clock_timestamp()))
        assert event.last_error_code == "DELIVERY_FAILED"
        assert db.get(ClassPost, post.id) is not None
    assert "test-only-secret" not in caplog.text
    monkeypatch.setattr(NotificationRepository, "create", original)
    assert drain_outbox(session_factory=system.factory) == 0
    with system.factory.begin() as db:
        db.execute(
            update(OutboxEvent).values(available_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert drain_outbox(session_factory=system.factory) == 1
    assert len(_rows(system)) == 2


def test_duplicate_version_replay_and_out_of_order_do_not_overwrite_or_duplicate(system):
    for version in (10, 9, 10):
        _version_event(system, version)
    assert drain_outbox(session_factory=system.factory) == 3
    rows = _rows(system, system.users["student"].id)
    assert sorted(row.payload_json["version"] for row in rows) == [9, 10]
    assert len({row.dedup_key for row in rows}) == 2


def test_feed_comment_deadline_scope_and_revoked_resource_access(system):
    post = _post(system)
    CommentsService(system.session).create_comment(
        system.class_id,
        post.id,
        CommentCreateRequest(body="Synthetic reply"),
        system.users["student"],
    )
    now = datetime.now(UTC)
    upsert_learning_deadline(
        system.session,
        class_id=system.class_id,
        external_ref="test-deadline",
        title="Synthetic deadline",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
        version=1,
    )
    assert drain_outbox(session_factory=system.factory) == 3
    assert len(_rows(system, system.users["teacher"].id, "SOCIAL_COMMENT_CREATED")) == 1
    assert len(_rows(system, system.users["student2"].id, "SOCIAL_COMMENT_CREATED")) == 0
    assert len(_rows(system, system.users["student"].id, "SOCIAL_POST_CREATED")) == 1
    assert len(_rows(system, system.users["admin"].id)) == 0
    assert len(_rows(system, system.users["outsider"].id)) == 0
    for row in _rows(system):
        assert not (
            {"body", "title", "external_ref", "recipient_ids", "school_id"}
            & row.payload_json.keys()
        )
    system.classroom.end_member(system.class_id, system.users["admin"], system.users["student"].id)
    with pytest.raises(AppError) as hidden:
        FeedService(system.session).list_posts(
            system.class_id, Pagination(limit=20, cursor=None), system.users["student"]
        )
    assert hidden.value.status_code == 404
    # The historical notification does not confer rights to the post.
    assert (
        NotificationService(system.session)
        .list_notifications(system.users["student"].id, Pagination(limit=20, cursor=None))
        .items
    )


def test_late_joiner_not_in_snapshot_and_revoked_user_not_delivered_new_content(system):
    _post(system)
    system.classroom.add_member(system.class_id, system.users["admin"], system.users["late"].id)
    system.classroom.end_member(system.class_id, system.users["admin"], system.users["student"].id)
    # Recipient revocation is independent of clock/poll scheduling. Select an
    # explicitly due fixture, while leaving retry attempts/backoff tests unchanged.
    with system.factory.begin() as db:
        db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.attempts == 0)
            .values(available_at=func.now() - timedelta(days=1))
        )
    drain_outbox(session_factory=system.factory)
    assert not _rows(system, system.users["late"].id, "SOCIAL_POST_CREATED")
    assert not _rows(system, system.users["student"].id, "SOCIAL_POST_CREATED")
    with system.factory() as db:
        timing = db.execute(
            text(
                "SELECT event_type,attempts,available_at,clock_timestamp(),published_at FROM core.outbox_events"
            )
        ).all()
    assert len(_rows(system, system.users["student2"].id, "SOCIAL_POST_CREATED")) == 1, timing


def test_teacher_replacement_and_archive_notify_affected_users(system):
    system.classroom.set_teachers(
        system.class_id,
        system.users["admin"],
        TeachingAssignmentsRequest(primary_lecturer_id=system.users["teacher2"].id),
    )
    system.classroom.set_archived(system.class_id, system.users["admin"], archived=True)
    drain_outbox(session_factory=system.factory)
    assert len(_rows(system, system.users["teacher"].id, "CLASS_TEACHERS_CHANGED")) == 1
    assert len(_rows(system, system.users["teacher2"].id, "CLASS_TEACHERS_CHANGED")) == 1
    assert (
        _rows(system, system.users["student"].id, "CLASS_STATUS_CHANGED")[0].payload_json["status"]
        == "ARCHIVED"
    )


def test_transfer_notification_only_targets_transferred_student(system):
    destination = system.classroom.create_class(
        system.users["admin"],
        ClassCreateRequest(
            course_id=system.course_id,
            name="Destination",
            academic_year="2026-2027",
            semester="1",
            grade_level=9,
            enrollment_mode=EnrollmentMode.MANUAL,
            primary_lecturer_id=system.users["teacher2"].id,
        ),
    )
    system.classroom.transfer(
        system.class_id, destination.id, system.users["student"].id, system.users["admin"]
    )
    drain_outbox(session_factory=system.factory)
    rows = _rows(system, event_type="CLASS_STUDENT_TRANSFERRED")
    assert [row.recipient_id for row in rows] == [system.users["student"].id]
    assert rows[0].payload_json["destination_class_id"] == str(destination.id)


def test_homeroom_transfer_uses_own_school_scope(system):
    rooms = [
        system.classroom.create_homeroom(
            system.users["admin"],
            HomeroomCreateRequest(name=name, grade_level=9, academic_year="2026-2027"),
        )
        for name in ("9A", "9B")
    ]
    system.classroom.set_roster(system.users["admin"], rooms[0].id, [system.users["student"].id])
    system.classroom.transfer_homeroom_student(
        rooms[0].id, rooms[1].id, system.users["student"].id, system.users["admin"]
    )
    drain_outbox(session_factory=system.factory)
    rows = _rows(system, event_type="HOMEROOM_STUDENT_TRANSFERRED")
    assert [row.recipient_id for row in rows] == [system.users["student"].id]
    assert rows[0].payload_json["homeroom_id"] == str(rooms[0].id)


def test_malformed_event_retries_without_leaking_and_unknown_event_is_left_for_its_consumer(
    system, caplog
):
    invalid_id = _version_event(system, 9)
    with system.factory.begin() as db:
        event = db.get(OutboxEvent, invalid_id)
        event.payload_json = {**event.payload_json, "token": "test-only-do-not-log"}
        unknown = record_outbox_event(
            db, event_type="FUTURE_OTHER_CONSUMER", aggregate_id=system.class_id, payload_json={}
        )
        unknown_id = unknown.id
    _post(system)
    assert drain_outbox(session_factory=system.factory) == 1
    with system.factory() as db:
        invalid = db.get(OutboxEvent, invalid_id)
        assert invalid.attempts == 1 and invalid.last_error_code == "INVALID_EVENT"
        assert db.get(OutboxEvent, unknown_id).published_at is None
        assert db.get(OutboxEvent, unknown_id).attempts == 0
    assert "test-only-do-not-log" not in caplog.text


def test_http_recipient_only_pagination_mark_read_all_and_current_account_status(
    system, monkeypatch
):
    monkeypatch.setattr(settings, "secret_key", SecretStr("test-only-signing-key-" + "x" * 32))
    for _ in range(3):
        _post(system)
    drain_outbox(session_factory=system.factory)
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)

    def db():
        with system.factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    student = system.users["student"]
    headers = {"Authorization": "Bearer " + create_access_token(student.id, student.roles, 1)}
    other_headers = {
        "Authorization": "Bearer "
        + create_access_token(system.users["outsider"].id, ["STUDENT"], 1)
    }
    with TestClient(app) as client:
        first = client.get("/api/v1/notifications?limit=2", headers=headers).json()
        assert first["unread_count"] == 3 and len(first["items"]) == 2
        second = client.get(
            f"/api/v1/notifications?limit=2&cursor={first['next_cursor']}", headers=headers
        ).json()
        assert len(second["items"]) == 1 and second["next_cursor"] is None
        assert len({row["id"] for row in first["items"] + second["items"]}) == 3
        notification_id = first["items"][0]["id"]
        assert (
            client.patch(
                f"/api/v1/notifications/{notification_id}/read", headers=other_headers
            ).status_code
            == 404
        )
        assert (
            client.patch(f"/api/v1/notifications/{uuid4()}/read", headers=headers).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/notifications?cursor={first['next_cursor']}", headers=other_headers
            ).status_code
            == 400
        )
        assert (
            client.patch(
                f"/api/v1/notifications/{notification_id}/read", headers=headers
            ).status_code
            == 200
        )
        with system.factory() as check:
            read_at = check.get(Notification, notification_id).read_at
        assert (
            client.patch(
                f"/api/v1/notifications/{notification_id}/read", headers=headers
            ).status_code
            == 200
        )
        with system.factory() as check:
            assert check.get(Notification, notification_id).read_at == read_at
        assert client.get("/api/v1/notifications", headers=headers).json()["unread_count"] == 2
        assert client.post("/api/v1/notifications/read-all", headers=headers).status_code == 204
        assert client.get("/api/v1/notifications", headers=headers).json()["unread_count"] == 0
        assert len(_rows(system, system.users["student2"].id)) == 3
        assert all(row.read_at is None for row in _rows(system, system.users["student2"].id))
        with system.factory.begin() as change:
            change.get(User, student.id).status = UserStatus.LOCKED
        assert client.get("/api/v1/notifications", headers=headers).status_code == 401


def test_concurrent_workers_skip_locked_and_deduplicate(system):
    for _ in range(8):
        _post(system)
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(lambda _: drain_outbox(session_factory=system.factory), range(4)))
    assert sum(counts) == 8
    rows = _rows(system)
    assert len(rows) == len({row.dedup_key for row in rows}) == 16


def test_read_all_serializes_with_delivery_and_later_arrival_stays_unread(system):
    _post(system)
    drain_outbox(session_factory=system.factory)
    recipient = system.users["student"].id
    acquired, release, writer_started, writer_done = Event(), Event(), Event(), Event()

    def reader():
        with system.factory.begin() as session:
            repository = NotificationRepository(session)
            repository.lock_recipient(recipient)
            acquired.set()
            assert release.wait(10)
            repository.mark_all_read(recipient)

    def writer():
        writer_started.set()
        with system.factory.begin() as session:
            NotificationRepository(session).create(
                recipient_id=recipient,
                event_type="CLASS_STATUS_CHANGED",
                payload={"class_id": str(system.class_id)},
                dedup_key=uuid4().hex,
            )
        writer_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = pool.submit(reader)
        assert acquired.wait(10)
        write_future = pool.submit(writer)
        assert writer_started.wait(10)
        assert not writer_done.wait(0.2)
        release.set()
        read_future.result(timeout=10)
        write_future.result(timeout=10)
    rows = _rows(system, recipient)
    assert len(rows) == 2 and rows[0].read_at is not None and rows[1].read_at is None
    result = NotificationService(system.session).list_notifications(
        recipient, Pagination(limit=20, cursor=None)
    )
    assert result.unread_count == 1 and result.items[0].id == rows[1].id


def test_migration_roundtrip_preserves_legacy_outbox_and_refuses_inbox_data_loss(database):
    # Run the schema round trip before domain fixtures create tenant-scoped audit
    # data; later migrations correctly refuse to discard that scope.
    command.downgrade(database.config, "0010")
    legacy_id = uuid4()
    with database.factory.begin() as db:
        db.execute(
            text(
                "INSERT INTO core.outbox_events (id,event_type,aggregate_id,payload_json) "
                "VALUES (:id,'CLASS_STATUS_CHANGED',:aggregate_id,CAST(:payload AS jsonb))"
            ),
            {
                "id": legacy_id,
                "aggregate_id": str(uuid4()),
                "payload": '{"version":4}',
            },
        )
    command.upgrade(database.config, "head")
    command.check(database.config)
    rolling_id = uuid4()
    with database.factory.begin() as db:
        # A pre-upgrade app instance still uses the old INSERT column list.
        db.execute(
            text(
                "INSERT INTO core.outbox_events (id,event_type,aggregate_id,payload_json) "
                "VALUES (:id,'CLASS_STATUS_CHANGED',:aggregate_id,CAST(:payload AS jsonb))"
            ),
            {
                "id": rolling_id,
                "aggregate_id": str(uuid4()),
                "payload": '{"version":5}',
            },
        )
    with database.factory() as db:
        event = db.get(OutboxEvent, legacy_id)
        assert event.schema_version == 1 and event.attempts == 0
        assert event.payload_json["version"] == 4
        assert event.published_at is None
        assert db.get(OutboxEvent, rolling_id).schema_version == 1
    # Legacy events have no recipient snapshot; the worker must leave them
    # quarantined rather than deriving recipients from current membership.
    assert drain_outbox(session_factory=database.factory) == 0
    with database.factory() as db:
        for event_id in (legacy_id, rolling_id):
            event = db.get(OutboxEvent, event_id)
            assert event.attempts == 0 and event.published_at is None
    with database.factory.begin() as db:
        user = User(username="migration.student", email=None, password_hash="test-only-hash")
        db.add(user)
        db.flush()
        db.add(
            Notification(
                recipient_id=user.id,
                type="CLASS_STATUS_CHANGED",
                payload_json={},
                dedup_key=uuid4().hex,
            )
        )
    with pytest.raises(RuntimeError, match="preserve inbox data"):
        command.downgrade(database.config, "0010")
    assert len(_rows(database)) == 1
