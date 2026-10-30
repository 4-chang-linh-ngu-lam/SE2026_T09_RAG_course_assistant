"""Committed PostgreSQL transactions exercise constraints and Classroom locking."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.common.errors import AppError
from app.maintenance.database import seed_development
from app.modules.classroom.schemas import TeachingAssignmentsRequest
from app.modules.classroom.service import ClassroomService
from app.modules.identity.public import admin_actor


def test_concurrent_membership_assignment_and_history_persistence(current):
    with current.factory() as session, session.begin():
        seed_development(
            session,
            environment="test",
            expected_database=current.name,
            school_id=uuid4(),
            school_name="Concurrency School",
            admin_password=SecretStr(secrets.token_urlsafe(32)),
        )
    with current.engine.connect() as connection:
        klass = connection.scalar(
            text(
                "SELECT id FROM core.subject_classes WHERE grade_level=9 AND enrollment_mode='MANUAL'"
            )
        )
        admin = connection.scalar(
            text("SELECT id FROM core.users WHERE email='admin@seed.example.com'")
        )
        student = connection.scalar(
            text("SELECT id FROM core.users WHERE username='seed.student.2'")
        )
        lecturers = list(
            connection.scalars(
                text(
                    "SELECT id FROM core.users WHERE email IN ('primary@seed.example.com','assisting@seed.example.com') ORDER BY email"
                )
            )
        )
        before_events = connection.scalar(text("SELECT count(*) FROM core.outbox_events"))
        before_audit = connection.scalar(text("SELECT count(*) FROM core.audit_events"))
    barrier = Barrier(2)

    def enroll(_):
        barrier.wait(timeout=10)
        with current.factory() as session:
            actor = admin_actor(admin, session=session)
            return ClassroomService(session).add_member(klass, actor, student).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(enroll, range(2)))) == 1
    with current.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.class_memberships WHERE class_id=:id AND student_id=:student AND status='ACTIVE'"
                ),
                {"id": klass, "student": student},
            )
            == 1
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM core.outbox_events")) == before_events + 1
        )
        assert connection.scalar(text("SELECT count(*) FROM core.audit_events")) == before_audit + 1

    def assign(index):
        barrier.wait(timeout=10)
        with current.factory() as session:
            actor = admin_actor(admin, session=session)
            ClassroomService(session).set_teachers(
                klass,
                actor,
                TeachingAssignmentsRequest(
                    primary_lecturer_id=lecturers[index],
                    assisting_lecturer_ids=[lecturers[1 - index]],
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(assign, range(2)))
    with current.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.teaching_assignments WHERE class_id=:id AND role='PRIMARY' AND ended_at IS NULL"
                ),
                {"id": klass},
            )
            == 1
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.teaching_assignments WHERE class_id=:id AND ended_at IS NOT NULL"
                ),
                {"id": klass},
            )
            >= 2
        )
        history = connection.scalar(
            text("SELECT count(*) FROM core.class_memberships WHERE class_id=:id"), {"id": klass}
        )
    # Partial unique index and foreign keys enforce integrity independently of API validation.
    for command, params in [
        (
            "INSERT INTO core.class_memberships(class_id,student_id,source,status,joined_at) VALUES (:class,:student,'MANUAL','ACTIVE',now())",
            {"class": klass, "student": student},
        ),
        (
            "INSERT INTO core.teaching_assignments(class_id,lecturer_id,role,assigned_at) VALUES (:class,:student,'PRIMARY',now())",
            {"class": klass, "student": student},
        ),
        (
            "INSERT INTO core.class_memberships(class_id,student_id,source,status,joined_at) VALUES (:class,:student,'MANUAL','ACTIVE',now())",
            {"class": klass, "student": uuid4()},
        ),
        (
            "INSERT INTO core.calendar_events(class_id,title,origin,starts_at,ends_at) VALUES (:class,'Invalid','CORE',now(),now())",
            {"class": klass},
        ),
    ]:
        with pytest.raises(IntegrityError), current.engine.begin() as connection:
            connection.execute(text(command), params)
    # A School mismatch fails in the live workflow; the schema does not infer scope.
    other_school = uuid4()
    with current.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.schools(id,name) VALUES (:id,'Other synthetic school')"),
            {"id": other_school},
        )
        connection.execute(
            text("UPDATE core.users SET school_id=:school WHERE id=:id"),
            {"school": other_school, "id": student},
        )
    with pytest.raises(AppError) as denied, current.factory() as session:
        ClassroomService(session).add_member(klass, admin_actor(admin, session=session), student)
    assert denied.value.status_code in (403, 404)
    with current.factory() as session:
        actor = admin_actor(admin, session=session)
        ClassroomService(session).end_member(klass, actor, student)
    with current.engine.begin() as connection:
        connection.execute(
            text("UPDATE core.users SET status='LOCKED' WHERE id=:id"), {"id": student}
        )
    with current.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM core.class_memberships WHERE class_id=:id"),
                {"id": klass},
            )
            == history
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.class_memberships WHERE class_id=:id AND student_id=:student AND status='ENDED' AND ended_at IS NOT NULL"
                ),
                {"id": klass, "student": student},
            )
            == 1
        )
