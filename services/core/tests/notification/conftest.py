"""Real PostgreSQL transactions, HTTP authorization and concurrent workers.

TEST_DATABASE_URL must identify a disposable test server/account with CREATEDB.
Every test uses a fresh sibling database and drops only that generated database.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.common.config import settings
from app.common.outbox import OutboxEvent
from app.modules.classroom.models import EnrollmentMode
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    CourseCreateRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.identity.public import get_current_user_snapshot
from app.modules.notification.models import Notification
from app.modules.notification.worker import drain_outbox


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
