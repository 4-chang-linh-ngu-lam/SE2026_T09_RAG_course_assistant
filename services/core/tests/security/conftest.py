"""Disposable, committed PostgreSQL integration fixtures, real module boundaries."""

import os
import secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.security import create_access_token
from app.maintenance.database import seed_development
from app.modules.identity.idempotency import IdempotencyStore, get_idempotency_store
from app.modules.identity.public import get_current_user_snapshot
from app.modules.identity.rate_limit import RateLimiter, get_rate_limiter


@pytest.fixture
def backend(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to disposable PostgreSQL 16 with CREATEDB")
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    name = "test_security_" + uuid4().hex
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(
        make_url(url).set(database=name),
        hide_parameters=True,
        pool_size=20,
        max_overflow=0,
        pool_timeout=15,
    )
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    monkeypatch.setattr(settings, "database_url", engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(settings, "secret_key", SecretStr(secrets.token_urlsafe(48)))
    monkeypatch.setattr(settings, "internal_service_secret", SecretStr(secrets.token_urlsafe(48)))
    monkeypatch.setattr(settings, "cors_origins", ["https://testserver"])
    password = secrets.token_urlsafe(32)
    try:
        command.upgrade(config, "head")
        with factory() as db, db.begin():
            seed_development(
                db,
                environment="test",
                expected_database=name,
                school_id=uuid4(),
                school_name="Security Synthetic School",
                admin_password=SecretStr(password),
            )
        with factory() as db:
            rows = db.execute(text("SELECT id,coalesce(email,username) AS label FROM core.users"))
            users = {row.label: get_current_user_snapshot(db, row.id) for row in rows}
            classes = {
                f"{row.grade_level}:{row.enrollment_mode}": row.id
                for row in db.execute(
                    text("SELECT id,grade_level,enrollment_mode FROM core.subject_classes")
                )
            }
            rooms = {
                row.grade_level: row.id
                for row in db.execute(text("SELECT id,grade_level FROM core.homeroom_classes"))
            }

        storage = IdempotencyStore()
        limiter = RateLimiter()

        def make_app():
            app = FastAPI()
            register_error_handlers(app)
            register_routers(app)

            def dependency():
                with factory() as db:
                    yield db

            app.dependency_overrides[get_db] = dependency
            app.dependency_overrides[get_idempotency_store] = lambda: storage
            app.dependency_overrides[get_rate_limiter] = lambda: limiter
            return app

        app = make_app()

        def headers(label="admin@seed.example.com", **extra):
            user = users[label]
            return {
                "Authorization": "Bearer "
                + create_access_token(user.id, user.roles, user.session_version),
                "X-Admin-Reason": "ADMIN_INTERVENTION",
                **extra,
            }

        with TestClient(app, base_url="https://testserver") as client:
            yield SimpleNamespace(
                engine=engine,
                factory=factory,
                config=config,
                users=users,
                classes=classes,
                rooms=rooms,
                password=password,
                client=client,
                headers=headers,
                app=app,
                make_app=make_app,
                storage=storage,
            )
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()
