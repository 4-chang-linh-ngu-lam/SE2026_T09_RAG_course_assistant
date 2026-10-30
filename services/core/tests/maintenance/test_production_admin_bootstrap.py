import json

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.common.audit import AuditEvent
from app.common.config import settings
from app.maintenance.__main__ import main
from app.maintenance.database import bootstrap_production_admin
from app.modules.classroom.models import School
from app.modules.identity.models import (
    CredentialDelivery,
    Role,
    RoleAssignment,
    User,
    UserStatus,
)

SCHOOL_NAME = "Lumi Mock School"
ADMIN_EMAIL = "admin@lumi-mock.example.com"


def production_profile(database):
    return {
        "environment": "production",
        "expected_database": database.name,
        "expected_host": database.engine.url.host,
        "school_name": SCHOOL_NAME,
        "admin_email": ADMIN_EMAIL,
        "confirm_production_bootstrap": True,
    }


def smtp_ready(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_username", "sender@lumi-mock.example.com")
    monkeypatch.setattr(settings, "smtp_password", SecretStr("test-only-smtp-password"))
    monkeypatch.setattr(settings, "smtp_from", "sender@lumi-mock.example.com")


def test_production_mock_bootstrap_creates_one_pending_admin_and_replays(current, monkeypatch):
    smtp_ready(monkeypatch)
    profile = production_profile(current)
    with current.factory() as session, session.begin():
        created = bootstrap_production_admin(session, **profile)
    assert created["created"] is True
    assert created["status"] == UserStatus.PENDING_VERIFICATION
    assert "email" not in json.dumps(created)
    assert "token" not in json.dumps(created).casefold()

    with current.factory() as session:
        admin = session.get(User, created["admin_user_id"])
        school = session.get(School, created["school_id"])
        assert admin is not None and admin.email == ADMIN_EMAIL
        assert admin.school_id == school.id and school.name == SCHOOL_NAME
        assert session.scalar(
            select(RoleAssignment.id).where(
                RoleAssignment.user_id == admin.id, RoleAssignment.role == Role.ADMIN
            )
        )
        assert session.scalar(
            select(CredentialDelivery.id).where(CredentialDelivery.status == "PENDING")
        )
        marker = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "PRODUCTION_BOOTSTRAP_ADMIN",
                AuditEvent.target_id == admin.id,
            )
        )
        assert marker is not None and marker.school_id == school.id

    with current.factory() as session, session.begin():
        replay = bootstrap_production_admin(session, **profile)
    assert replay["created"] is False
    assert replay["school_id"] == created["school_id"]
    assert replay["admin_user_id"] == created["admin_user_id"]
    assert session_scalar(current, "SELECT count(*) FROM core.schools") == 1
    assert session_scalar(current, "SELECT count(*) FROM core.users") == 1
    assert (
        session_scalar(
            current,
            "SELECT count(*) FROM core.audit_events WHERE action='PRODUCTION_BOOTSTRAP_ADMIN'",
        )
        == 1
    )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"environment": "staging"}, "explicit Production confirmation"),
        ({"confirm_production_bootstrap": False}, "explicit Production confirmation"),
        ({"school_name": "Real School"}, "only permits Lumi Mock School"),
        ({"expected_database": "wrong_database"}, "database name mismatch"),
        ({"expected_host": "wrong.example"}, "database host mismatch"),
    ],
)
def test_production_mock_bootstrap_rejects_unsafe_profile(current, monkeypatch, change, match):
    smtp_ready(monkeypatch)
    with (
        pytest.raises(ValueError, match=match),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_production_admin(session, **{**production_profile(current), **change})
    assert session_scalar(current, "SELECT count(*) FROM core.schools") == 0
    assert session_scalar(current, "SELECT count(*) FROM core.users") == 0


def test_production_mock_bootstrap_requires_smtp_and_empty_core(current, monkeypatch):
    profile = production_profile(current)
    monkeypatch.setattr(settings, "smtp_host", None)
    with (
        pytest.raises(ValueError, match="Configure the production SMTP sender"),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_production_admin(session, **profile)
    assert session_scalar(current, "SELECT count(*) FROM core.schools") == 0

    smtp_ready(monkeypatch)
    with current.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.schools(id,name) VALUES (gen_random_uuid(),'Pre-existing')")
        )
    with (
        pytest.raises(ValueError, match="empty Core database"),
        current.factory() as session,
        session.begin(),
    ):
        bootstrap_production_admin(session, **profile)
    assert session_scalar(current, "SELECT count(*) FROM core.users") == 0


def test_production_bootstrap_cli_uses_separate_database_target(current, monkeypatch, capsys):
    smtp_ready(monkeypatch)
    monkeypatch.setenv(
        "PRODUCTION_DATABASE_URL", current.engine.url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv("PRODUCTION_DATABASE_HOST", current.engine.url.host)
    monkeypatch.setenv("PRODUCTION_BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("PRODUCTION_BOOTSTRAP_SCHOOL_NAME", SCHOOL_NAME)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ignored:ignored@invalid/ignored")
    assert (
        main(
            [
                "bootstrap-production-admin",
                "--environment",
                "production",
                "--expected-database",
                current.name,
                "--expected-host",
                current.engine.url.host,
                "--confirm-production-bootstrap",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["created"] is True
    assert ADMIN_EMAIL not in output.out + output.err
    assert "password" not in output.out.casefold() + output.err.casefold()


def session_scalar(database, sql):
    with database.engine.connect() as connection:
        return connection.scalar(text(sql))
