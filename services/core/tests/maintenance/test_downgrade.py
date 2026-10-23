from io import StringIO
from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text


@pytest.mark.parametrize(
    "insert,target,match",
    [
        ("INSERT INTO core.schools(name) VALUES ('Preserved')", "0007", "core.schools"),
        (
            "INSERT INTO core.users(email,password_hash,username) VALUES ('test@example.com','test-hash','preserved')",
            "0005",
            "Student identifiers",
        ),
        (
            "INSERT INTO core.audit_events(action,target_type,target_id,correlation_id,metadata_json) VALUES ('TEST','USER',gen_random_uuid(),gen_random_uuid(),'{}')",
            "0001",
            "core.audit_events",
        ),
        (
            "INSERT INTO core.outbox_events(event_type,aggregate_id,payload_json,schema_version) VALUES ('TEST','test','{}',2)",
            "0010",
            "outbox envelope/retry",
        ),
        (
            "INSERT INTO core.outbox_events(event_type,aggregate_id,payload_json,attempts) VALUES ('TEST','test','{}',1)",
            "0010",
            "outbox envelope/retry",
        ),
        (
            "INSERT INTO core.outbox_events(event_type,aggregate_id,payload_json,last_error_code) VALUES ('TEST','test','{}','ERROR')",
            "0010",
            "outbox envelope/retry",
        ),
        (
            "INSERT INTO core.outbox_events(event_type,aggregate_id,payload_json,available_at) VALUES ('TEST','test','{}',now()+interval '1 day')",
            "0010",
            "outbox envelope/retry",
        ),
    ],
)
def test_incompatible_downgrade_refuses_before_any_ddl(current, insert, target, match):
    with current.engine.begin() as connection:
        connection.execute(text(insert))
    head = ScriptDirectory.from_config(current.config).get_current_head()
    with pytest.raises(RuntimeError, match=match):
        command.downgrade(current.config, target)
    with current.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM core.alembic_version")) == head
        assert (
            connection.scalar(text("SELECT to_regclass('core.student_import_batches')")) is not None
        )
    command.check(current.config)


def test_compatible_legacy_rows_roundtrip_to_0004(current):
    user_id = uuid4()
    with current.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash,status) VALUES (:id,'legacy@example.com','preserved-hash','LOCKED')"
            ),
            {"id": user_id},
        )
        connection.execute(
            text("INSERT INTO core.data_requests(user_id,request_type) VALUES (:id,'EXPORT')"),
            {"id": user_id},
        )
    command.downgrade(current.config, "0004")
    command.upgrade(current.config, "head")
    with current.engine.connect() as connection:
        assert tuple(
            connection.execute(text("SELECT id,password_hash,status FROM core.users")).one()
        ) == (user_id, "preserved-hash", "LOCKED")
        assert connection.scalar(text("SELECT request_type FROM core.data_requests")) == "EXPORT"
    command.check(current.config)


def test_offline_downgrade_refuses_and_upgrade_range_generates_sql(current):
    current.config.output_buffer = StringIO()
    with pytest.raises(RuntimeError, match="Offline downgrade"):
        command.downgrade(current.config, "0012:0011", sql=True)
    assert "DROP TABLE" not in current.config.output_buffer.getvalue()
    command.upgrade(current.config, "0004:head", sql=True)
    assert "CREATE TABLE core.notifications" in current.config.output_buffer.getvalue()
