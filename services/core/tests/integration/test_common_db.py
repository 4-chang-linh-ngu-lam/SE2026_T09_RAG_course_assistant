import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.common.audit import AuditEvent, AuditMetadata, record_audit
from app.common.config import settings
from app.common.db import transaction


def test_audit_migration_and_transactions(monkeypatch):
    """TEST_DATABASE_URL must point to a disposable Core test database."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    monkeypatch.setattr(settings, "database_url", database_url)
    core_dir = Path(__file__).resolve().parents[2]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "migrations"))
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(database_url, connect_args={"options": "-c timezone=UTC"})
    correlation_id = uuid4()
    try:
        with Session(engine) as session:
            with transaction(session):
                event = record_audit(
                    session,
                    actor_id=None,
                    action="USER_LOCKED",
                    target_type="USER",
                    target_id=uuid4(),
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(new_status="LOCKED"),
                )
            assert isinstance(event.id, type(uuid4()))
            assert event.created_at.utcoffset().total_seconds() == 0
            assert event.updated_at.utcoffset().total_seconds() == 0
        with Session(engine) as session:
            committed = session.scalar(
                select(AuditEvent).where(AuditEvent.correlation_id == correlation_id)
            )
            assert committed is not None
            assert committed.metadata_json["new_status"] == "LOCKED"
            assert session.scalar(text("SELECT version_num FROM core.alembic_version")) == (
                ScriptDirectory.from_config(config).get_current_head()
            )
        rollback_id = uuid4()
        with Session(engine) as session, pytest.raises(RuntimeError), transaction(session):
            record_audit(
                session,
                actor_id=None,
                action="USER_LOCKED",
                target_type="USER",
                target_id=uuid4(),
                correlation_id=rollback_id,
                metadata_json=AuditMetadata(),
            )
            session.flush()
            raise RuntimeError("Abort transaction after insert")
        with Session(engine) as session:
            assert (
                session.scalar(select(AuditEvent).where(AuditEvent.correlation_id == rollback_id))
                is None
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(AuditEvent).where(AuditEvent.correlation_id == correlation_id)
            )
        engine.dispose()
