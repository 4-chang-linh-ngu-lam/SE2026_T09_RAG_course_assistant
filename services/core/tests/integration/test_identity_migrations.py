import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.common.config import settings


@pytest.fixture
def migration_db(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    # Separate database: migration round trips never touch the suite's existing test data.
    database_name = "identity_migration_" + uuid4().hex
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    database_url = make_url(url).set(database=database_name).render_as_string(hide_password=False)
    core_dir = Path(__file__).resolve().parents[2]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "migrations"))
    monkeypatch.setattr(settings, "database_url", database_url)
    engine = create_engine(database_url, hide_parameters=True)
    try:
        yield config, engine
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
        parent.dispose()


def test_upgrade_preserves_legacy_identity_and_supports_no_email(migration_db):
    config, engine = migration_db
    command.upgrade(config, "0004")
    legacy_id, student_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash,status,session_version) "
                "VALUES (:id,'legacy@example.com','unchanged-hash','LOCKED',7)"
            ),
            {"id": legacy_id},
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT email,password_hash,status,session_version,username,school_id "
                "FROM core.users WHERE id=:id"
            ),
            {"id": legacy_id},
        ).one()
        assert tuple(row) == ("legacy@example.com", "unchanged-hash", "LOCKED", 7, None, None)
        connection.execute(
            text(
                "INSERT INTO core.users(id,username,password_hash) "
                "VALUES (:id,'student.test','test-only-hash')"
            ),
            {"id": student_id},
        )
        connection.execute(
            text("INSERT INTO core.data_requests(user_id,request_type) VALUES (:id,'CORRECTION')"),
            {"id": student_id},
        )
    # Database constraints independently enforce uniqueness/normalization.
    for username in ("student.test", "UPPERCASE"):
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text("INSERT INTO core.users(username,password_hash) VALUES (:username,'hash')"),
                {"username": username},
            )
    with pytest.raises(DBAPIError):
        command.downgrade(config, "0005")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM core.users WHERE id=:id"), {"id": student_id}
            )
            == 1
        )
        assert connection.scalar(text("SELECT version_num FROM core.alembic_version")) == "0007"


def test_new_identity_migration_round_trip(migration_db):
    config, _ = migration_db
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "0004")
    command.upgrade(config, "head")
    command.check(config)
