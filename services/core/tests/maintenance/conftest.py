import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.common.config import settings


@pytest.fixture
def database(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL 16 account with CREATEDB")
    name = "test_maintenance_" + uuid4().hex
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(make_url(url).set(database=name), hide_parameters=True)
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    monkeypatch.setattr(settings, "database_url", engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(
        settings,
        "secret_key",
        SecretStr("test-only-maintenance-signing-key-" + "x" * 32),
    )
    try:
        yield SimpleNamespace(
            engine=engine,
            config=config,
            name=name,
            factory=sessionmaker(engine, autoflush=False, expire_on_commit=False),
        )
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()


@pytest.fixture
def current(database):
    command.upgrade(database.config, "head")
    return database
