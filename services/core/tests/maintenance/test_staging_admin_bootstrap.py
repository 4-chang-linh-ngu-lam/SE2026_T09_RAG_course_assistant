import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.common.audit import AuditEvent
from app.common.config import settings
from app.maintenance.__main__ import _session_scope, main
from app.maintenance.database import bootstrap_staging_admin
from app.modules.classroom.models import School
from app.modules.identity.models import (
    CredentialDelivery,
    OneTimeToken,
    Role,
    RoleAssignment,
    TokenPurpose,
    User,
)

ADMIN_EMAIL = "admin@staging.example.com"
SCHOOL_NAME = "Lumi Staging"


def counts(engine):
    tables = (
        "schools",
        "users",
        "role_assignments",
        "one_time_tokens",
        "credential_deliveries",
        "audit_events",
    )
    with engine.connect() as connection:
        return {
            table: connection.scalar(text(f"SELECT count(*) FROM core.{table}")) for table in tables
        }


def staging_profile(database):
    return {
        "environment": "staging",
        "expected_database": database.name,
        "expected_host": database.engine.url.host,
        "school_name": SCHOOL_NAME,
        "admin_email": ADMIN_EMAIL,
        "confirm_staging_bootstrap": True,
    }


def smtp_ready(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_username", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "smtp_password", SecretStr("test-only-smtp-app-password"))
    monkeypatch.setattr(settings, "smtp_from", ADMIN_EMAIL)


def test_staging_session_scope_requires_dedicated_target(monkeypatch):
    monkeypatch.delenv("STAGING_DATABASE_URL", raising=False)
    monkeypatch.delenv("STAGING_DATABASE_HOST", raising=False)
    args = SimpleNamespace(command="bootstrap-staging-admin", expected_host="staging.example")
    with (
        pytest.raises(ValueError, match="STAGING_DATABASE_URL and STAGING_DATABASE_HOST"),
        _session_scope(args),
    ):
        pytest.fail("no session should be opened without the staging database target")


def test_staging_session_scope_uses_only_confirmed_staging_url(monkeypatch):
    staging_url = "postgresql://staging:placeholder@staging.example/staging_db"
    monkeypatch.setenv("STAGING_DATABASE_URL", staging_url)
    monkeypatch.setenv("STAGING_DATABASE_HOST", "staging.example")
    engines = []
    disposed = []

    class SessionContext:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        @contextmanager
        def begin(self):
            yield

    def create_engine(url, **_):
        engine = SimpleNamespace(dispose=lambda: disposed.append(True))
        engines.append((url, engine))
        return engine

    monkeypatch.setattr("app.maintenance.__main__.create_engine", create_engine)
    monkeypatch.setattr("app.maintenance.__main__.sessionmaker", lambda **_: SessionContext)
    monkeypatch.setattr(
        "app.maintenance.__main__.SessionLocal",
        lambda: pytest.fail("staging bootstrap must not use the generic DATABASE_URL"),
    )
    args = SimpleNamespace(command="bootstrap-staging-admin", expected_host="staging.example")

    with _session_scope(args) as session:
        assert isinstance(session, SessionContext)

    assert len(engines) == 1
    url, _ = engines[0]
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "staging.example" and url.database == "staging_db"
    assert disposed == [True]


def test_staging_session_scope_rejects_host_before_connecting(monkeypatch):
    monkeypatch.setenv(
        "STAGING_DATABASE_URL",
        "postgresql+psycopg://staging:placeholder@staging.example/staging_db",
    )
    monkeypatch.setenv("STAGING_DATABASE_HOST", "production.example")
    monkeypatch.setattr(
        "app.maintenance.__main__.create_engine",
        lambda *_args, **_kwargs: pytest.fail("host mismatch must fail before opening a DB"),
    )
    args = SimpleNamespace(command="bootstrap-staging-admin", expected_host="staging.example")
    with pytest.raises(ValueError, match="database host mismatch"), _session_scope(args):
        pytest.fail("no session should be opened on a mismatched host")


@pytest.mark.parametrize("parameter", ["host", "hostaddr", "service", "servicefile"])
def test_staging_session_scope_rejects_connection_target_overrides(monkeypatch, parameter):
    monkeypatch.setenv(
        "STAGING_DATABASE_URL",
        f"postgresql://staging:placeholder@staging.example/staging_db?{parameter}=other.example",
    )
    monkeypatch.setenv("STAGING_DATABASE_HOST", "staging.example")
    monkeypatch.setattr(
        "app.maintenance.__main__.create_engine",
        lambda *_args, **_kwargs: pytest.fail("target override must fail before connecting"),
    )
    args = SimpleNamespace(command="bootstrap-staging-admin", expected_host="staging.example")
    with (
        pytest.raises(ValueError, match="must not override its connection target"),
        _session_scope(args),
    ):
        pytest.fail("no session should be opened for a redirected target")


def test_staging_bootstrap_creates_only_pending_admin_and_invitation(current, monkeypatch):
    smtp_ready(monkeypatch)
    profile = staging_profile(current)
    with current.factory() as session, session.begin():
        result = bootstrap_staging_admin(session, **profile)

    assert result["created"] is True
    assert result["status"] == "PENDING_VERIFICATION"
    assert "token" not in json.dumps(result).lower()
    assert ADMIN_EMAIL not in json.dumps(result)
    with current.factory() as session:
        user = session.get(User, result["admin_user_id"])
        school = session.get(School, result["school_id"])
        assert user is not None and user.email == ADMIN_EMAIL and user.school_id == school.id
        assert str(user.status) == "PENDING_VERIFICATION" and user.email_verified_at is None
        assert (
            session.scalar(
                select(RoleAssignment.id).where(
                    RoleAssignment.user_id == user.id, RoleAssignment.role == Role.ADMIN
                )
            )
            is not None
        )
        token = session.scalar(
            select(OneTimeToken).where(
                OneTimeToken.user_id == user.id,
                OneTimeToken.purpose == TokenPurpose.ADMIN_INVITATION,
            )
        )
        assert token is not None and token.consumed_at is None and len(token.token_hash) == 64
        delivery = session.scalar(
            select(CredentialDelivery).where(CredentialDelivery.token_id == token.id)
        )
        assert delivery is not None and delivery.status == "PENDING"
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "STAGING_BOOTSTRAP_ADMIN", AuditEvent.target_id == user.id
            )
        )
        assert event is not None and event.actor_id is None and event.school_id == school.id
        assert school.name == SCHOOL_NAME


def test_staging_bootstrap_retry_is_idempotent_and_profile_bound(current, monkeypatch):
    smtp_ready(monkeypatch)
    profile = staging_profile(current)
    with current.factory() as session, session.begin():
        created = bootstrap_staging_admin(session, **profile)
    before = counts(current.engine)
    with current.factory() as session, session.begin():
        retried = bootstrap_staging_admin(session, **profile)
    assert retried["created"] is False
    assert retried["school_id"] == created["school_id"]
    assert retried["admin_user_id"] == created["admin_user_id"]
    with (
        pytest.raises(ValueError, match="marker does not match"),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_staging_admin(session, **{**profile, "school_name": "Other School"})
    assert counts(current.engine) == before


def test_concurrent_staging_bootstrap_creates_only_one_invitation(current, monkeypatch):
    smtp_ready(monkeypatch)
    profile = staging_profile(current)
    barrier = Barrier(2)

    def run():
        with current.factory() as session, session.begin():
            barrier.wait(timeout=10)
            return bootstrap_staging_admin(session, **profile)["created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == [False, True]
    result = counts(current.engine)
    assert result["schools"] == 1
    assert result["users"] == 1
    assert result["role_assignments"] == 1
    assert result["one_time_tokens"] == 1
    assert result["credential_deliveries"] == 1
    assert result["audit_events"] == 1


@pytest.mark.parametrize(
    "change,match",
    [
        ({"environment": "production"}, "explicit staging confirmation"),
        ({"confirm_staging_bootstrap": False}, "explicit staging confirmation"),
        ({"expected_database": "wrong"}, "database name mismatch"),
        ({"expected_host": "other.example"}, "database host mismatch"),
    ],
)
def test_staging_bootstrap_rejects_wrong_environment_or_database(
    current, monkeypatch, change, match
):
    smtp_ready(monkeypatch)
    with (
        pytest.raises(ValueError, match=match),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_staging_admin(session, **{**staging_profile(current), **change})
    assert not any(counts(current.engine).values())


def test_staging_bootstrap_requires_smtp_and_empty_core(current, monkeypatch):
    profile = staging_profile(current)
    monkeypatch.setattr(settings, "smtp_host", None)
    with (
        pytest.raises(ValueError, match="Configure the staging SMTP"),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_staging_admin(session, **profile)
    assert not any(counts(current.engine).values())

    smtp_ready(monkeypatch)
    with current.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.schools(id,name) VALUES (gen_random_uuid(),'Existing')")
        )
    with (
        pytest.raises(ValueError, match="empty Core database"),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_staging_admin(session, **profile)
    assert counts(current.engine)["schools"] == 1 and counts(current.engine)["users"] == 0


def test_staging_bootstrap_cli_outputs_only_safe_identifiers(current, monkeypatch, capsys):
    smtp_ready(monkeypatch)
    monkeypatch.setenv("STAGING_BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("STAGING_BOOTSTRAP_SCHOOL_NAME", SCHOOL_NAME)
    monkeypatch.setenv(
        "STAGING_DATABASE_URL", current.engine.url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv("STAGING_DATABASE_HOST", current.engine.url.host)
    monkeypatch.setattr(
        "app.maintenance.__main__.SessionLocal",
        lambda: pytest.fail("staging bootstrap must not use the generic DATABASE_URL"),
    )
    result = main(
        [
            "bootstrap-staging-admin",
            "--environment",
            "staging",
            "--expected-database",
            current.name,
            "--expected-host",
            current.engine.url.host,
            "--confirm-staging-bootstrap",
        ]
    )
    captured = capsys.readouterr()
    assert result == 0
    assert ADMIN_EMAIL not in captured.out + captured.err
    assert "token" not in (captured.out + captured.err).lower()
    assert json.loads(captured.out)["status"] == "PENDING_VERIFICATION"


def test_staging_bootstrap_cli_rejects_target_host_mismatch(current, monkeypatch, capsys):
    monkeypatch.setenv(
        "STAGING_DATABASE_URL", current.engine.url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv("STAGING_DATABASE_HOST", "other.example")
    before = counts(current.engine)
    result = main(
        [
            "bootstrap-staging-admin",
            "--environment",
            "staging",
            "--expected-database",
            current.name,
            "--expected-host",
            current.engine.url.host,
            "--confirm-staging-bootstrap",
        ]
    )
    captured = capsys.readouterr()
    assert result == 1
    assert "database host mismatch" in captured.err
    password = current.engine.url.password
    assert not password or password not in captured.out + captured.err
    assert counts(current.engine) == before
