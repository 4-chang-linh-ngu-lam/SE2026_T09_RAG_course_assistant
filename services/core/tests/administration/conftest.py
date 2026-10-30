import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.common.security import create_access_token
from app.modules.administration.service import AdministrationService
from app.modules.classroom.models import School
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.identity.public import get_current_user_snapshot, get_token_sender


@pytest.fixture
def database(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL account with CREATEDB")
    name = "administration_test_" + uuid4().hex
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    test_url = make_url(url).set(database=name)
    engine = create_engine(
        test_url, hide_parameters=True, connect_args={"options": "-c timezone=UTC"}
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
    )
    monkeypatch.setattr(settings, "database_url", test_url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, "head")
        command.check(config)
        yield SimpleNamespace(
            engine=engine,
            factory=sessionmaker(engine, autoflush=False, expire_on_commit=False),
            config=config,
        )
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()


@pytest.fixture
def system(database, monkeypatch):
    monkeypatch.setattr(
        settings, "secret_key", SecretStr("test-only-administration-signing-key-" + "x" * 32)
    )
    with database.factory() as session:
        school_id, other_school = uuid4(), uuid4()
        session.add_all(
            [
                School(id=school_id, name="Synthetic administration school"),
                School(id=other_school, name="Synthetic other school"),
            ]
        )
        session.flush()
        users = {}
        for name, role, scope in (
            ("admin", Role.ADMIN, school_id),
            ("admin2", Role.ADMIN, school_id),
            ("teacher", Role.LECTURER, school_id),
            ("student", Role.STUDENT, school_id),
            ("other_admin", Role.ADMIN, other_school),
            ("other_student", Role.STUDENT, other_school),
            ("unscoped", Role.ADMIN, None),
        ):
            id = uuid4()
            session.add(
                User(
                    id=id,
                    email=f"{id}@example.com" if role != Role.STUDENT else None,
                    username="student." + id.hex if role == Role.STUDENT else None,
                    password_hash="test-only-noncredential-hash",
                    display_name=name,
                    school_id=scope,
                    status=UserStatus.ACTIVE,
                    email_verified_at=datetime.now(UTC) if role != Role.STUDENT else None,
                    activated_at=datetime.now(UTC) if role == Role.STUDENT else None,
                )
            )
            session.flush()
            session.add(RoleAssignment(user_id=id, role=role))
            session.flush()
            users[name] = get_current_user_snapshot(session, id)
        session.commit()
        app = FastAPI()
        register_error_handlers(app)
        register_routers(app)

        def db():
            with database.factory() as current:
                yield current

        app.dependency_overrides[get_db] = db

        class Sender:
            fail = False

            def __init__(self):
                self.deliveries = []
                self.attempts = []

            def send(self, delivery):
                self.attempts.append(delivery)
                if self.fail:
                    raise AppError(503, "Synthetic mail unavailable")
                self.deliveries.append(delivery)

        sender = Sender()
        app.dependency_overrides[get_token_sender] = lambda: sender
        with TestClient(app) as client:

            def headers(name="admin", **kwargs):
                user = users[name]
                return {
                    "Authorization": "Bearer "
                    + create_access_token(user.id, user.roles, user.session_version),
                    "X-Admin-Reason": "ADMIN_INTERVENTION",
                    **kwargs,
                }

            yield SimpleNamespace(
                **vars(database),
                session=session,
                service=AdministrationService(session, uuid4()),
                users=users,
                headers=headers,
                client=client,
                sender=sender,
                school_id=school_id,
            )
