import json
import os
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.common.audit import AuditEvent
from app.common.security import verify_password
from app.maintenance import database as maintenance
from app.maintenance.__main__ import main
from app.maintenance.database import MappingManifest, apply_mapping, mapping_plan, seed_development
from app.maintenance.migration_safety import TABLES_INTRODUCED
from app.model_registry import load_metadata


def profile(database):
    return {
        "environment": "test",
        "expected_database": database.name,
        "school_id": uuid4(),
        "school_name": "Synthetic Test School",
        "admin_password": SecretStr(secrets.token_urlsafe(32)),
    }


def counts(engine):
    with engine.connect() as connection:
        return {
            table.name: connection.scalar(select(text("count(*)")).select_from(table))
            for table in load_metadata().sorted_tables
        }


def test_seed_repeat_preserves_credentials_audit_and_outbox(current, monkeypatch, capsys):
    args = profile(current)
    with current.factory() as session, session.begin():
        assert seed_development(session, **args)["created"] is True
    before = counts(current.engine)
    with current.engine.connect() as connection:
        rows = connection.execute(text("SELECT password_hash FROM core.users")).scalars().all()
        assert len(set(rows)) == 6
        assert connection.scalar(text("SELECT count(*) FROM core.subject_classes")) == 14
        assert (
            connection.scalar(text("SELECT count(DISTINCT grade_level) FROM core.subject_classes"))
            == 7
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.teaching_assignments WHERE role='ASSISTING' AND ended_at IS NULL"
                )
            )
            == 14
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM core.users WHERE status='PENDING_VERIFICATION'")
            )
            == 1
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM core.users WHERE username IS NOT NULL AND activated_at IS NOT NULL"
                )
            )
            == 2
        )
        admin_hash = connection.scalar(
            text("SELECT password_hash FROM core.users WHERE email='admin@seed.example.com'")
        )
        assert verify_password(args["admin_password"].get_secret_value(), admin_hash)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM core.one_time_tokens WHERE consumed_at IS NOT NULL")
            )
            >= 4
        )
        assert before["audit_events"] > 0 and before["outbox_events"] > 0
    with current.factory() as session, session.begin():
        assert seed_development(session, **args)["created"] is False
    assert counts(current.engine) == before
    # CLI uses environment credentials and returns only identifiers/outcome.
    monkeypatch.setenv("CORE_SEED_ADMIN_PASSWORD", args["admin_password"].get_secret_value())
    monkeypatch.setattr("app.maintenance.__main__.SessionLocal", current.factory)
    assert (
        main(
            [
                "seed-dev",
                "--environment",
                "test",
                "--expected-database",
                current.name,
                "--school-id",
                str(args["school_id"]),
                "--school-name",
                args["school_name"],
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["created"] is False
    assert args["admin_password"].get_secret_value() not in output.out + output.err
    assert all(value not in output.out for value in rows)
    with (
        pytest.raises(ValueError, match="different profile"),
        current.factory() as session,
        session.begin(),
    ):
        seed_development(session, **{**args, "school_name": "Different"})
    command.check(current.config)


@pytest.mark.parametrize(
    "change,match",
    [
        ({"environment": "production"}, "restricted"),
        ({"expected_database": "wrong"}, "exact dedicated"),
        ({"admin_password": SecretStr("short")}, "password"),
    ],
)
def test_seed_rejects_unsafe_target_and_credentials(current, change, match):
    with pytest.raises(ValueError, match=match), current.factory() as session, session.begin():
        seed_development(session, **{**profile(current), **change})
    assert not any(counts(current.engine).values())


def test_seed_atomic_rollback_and_nonempty_refusal(current, monkeypatch):
    args = profile(current)

    def fail(**kwargs):
        raise RuntimeError("Synthetic classroom failure")

    monkeypatch.setattr(maintenance, "seed_dev_classroom", fail)
    with (
        pytest.raises(RuntimeError, match="Synthetic"),
        current.factory() as session,
        session.begin(),
    ):
        seed_development(session, **args)
    assert not any(counts(current.engine).values())
    with current.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.schools(id,name) VALUES (:id,'Existing')"), {"id": uuid4()}
        )
    with (
        pytest.raises(ValueError, match="empty Core"),
        current.factory() as session,
        session.begin(),
    ):
        seed_development(session, **args)
    assert counts(current.engine)["schools"] == 1


def test_concurrent_seed_serializes_and_never_duplicates(current):
    args = profile(current)
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=10)
        with current.factory() as session, session.begin():
            return seed_development(session, **args)["created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == [False, True]
    assert counts(current.engine)["users"] == 6


@pytest.mark.parametrize("checkpoint", ["0004", "head"])
def test_upgrade_and_reviewed_mapping_preserve_legacy_history(database, checkpoint):
    command.upgrade(database.config, checkpoint)
    user_id, school_id, token_id, session_id, request_id = [uuid4() for _ in range(5)]
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash,status,session_version) VALUES (:id,'legacy@example.com','unchanged-test-hash','LOCKED',7)"
            ),
            {"id": user_id},
        )
        connection.execute(
            text("INSERT INTO core.role_assignments(user_id,role) VALUES (:id,'STUDENT')"),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO core.one_time_tokens(id,user_id,purpose,token_hash,expires_at) VALUES (:id,:user,'PASSWORD_RESET',:hash,now()+interval '1 day')"
            ),
            {"id": token_id, "user": user_id, "hash": "t" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO core.auth_sessions(id,user_id,refresh_hash,family_id,expires_at) VALUES (:id,:user,:hash,:family,now()+interval '1 day')"
            ),
            {"id": session_id, "user": user_id, "hash": "r" * 64, "family": uuid4()},
        )
        connection.execute(
            text(
                "INSERT INTO core.data_requests(id,user_id,request_type,status,reason) VALUES (:id,:user,'EXPORT','IN_REVIEW','preserved test reason')"
            ),
            {"id": request_id, "user": user_id},
        )
        original = {
            table: connection.execute(text(f"SELECT * FROM core.{table}")).mappings().all()
            for table in (
                "users",
                "role_assignments",
                "one_time_tokens",
                "auth_sessions",
                "data_requests",
            )
        }
    command.upgrade(database.config, "head")
    command.check(database.config)
    with database.engine.connect() as connection:
        for table, rows in original.items():
            actual = connection.execute(text(f"SELECT * FROM core.{table}")).mappings().all()
            assert [{key: row[key] for key in rows[0]} for row in actual] == rows
    manifest = MappingManifest(
        schools={school_id: "Reviewed School"}, assignments={user_id: school_id}
    )
    with database.factory() as session:
        plan = mapping_plan(session, manifest)
        assert "MISSING_SCHOOL_SCOPE" in plan["users"][0]["issues"]
        assert "STUDENT_USERNAME_NOT_MIGRATED" in plan["users"][0]["issues"]
        assert "legacy@example.com" not in json.dumps(plan)
        assert "unchanged-test-hash" not in json.dumps(plan)
    with (
        pytest.raises(ValueError, match="approval mismatch"),
        database.factory() as session,
        session.begin(),
    ):
        apply_mapping(session, manifest, approved_sha256="unreviewed")
    assert counts(database.engine)["schools"] == 0
    with database.factory() as session, session.begin():
        result = apply_mapping(session, manifest, approved_sha256=plan["plan_sha256"])
        assert result["users"][0]["school_id"] == str(school_id)
        assert result["users"][0]["status"] == "LOCKED"
    with database.engine.connect() as connection:
        user = connection.execute(text("SELECT * FROM core.users")).mappings().one()
        assert (user["id"], user["password_hash"], user["status"], user["session_version"]) == (
            user_id,
            "unchanged-test-hash",
            "LOCKED",
            8,
        )
        assert user["username"] is None and user["activated_at"] is None
        assert connection.scalar(text("SELECT revoked_at IS NOT NULL FROM core.auth_sessions"))
        assert connection.scalar(text("SELECT id FROM core.one_time_tokens")) == token_id
        assert (
            connection.scalar(text("SELECT reason FROM core.data_requests"))
            == "preserved test reason"
        )
        assert (
            connection.scalar(select(AuditEvent.action).where(AuditEvent.target_id == user_id))
            == "LEGACY_ASSIGN_SCHOOL"
        )
    # An unchanged reviewed plan is a no-op for users and revocation.
    with database.factory() as session, session.begin():
        refreshed = mapping_plan(session, manifest)
        apply_mapping(session, manifest, approved_sha256=refreshed["plan_sha256"])
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT session_version FROM core.users")) == 8
    other_school = uuid4()
    with pytest.raises(ValueError, match="Cross-school"), database.factory() as session:
        mapping_plan(
            session,
            MappingManifest(schools={other_school: "Other"}, assignments={user_id: other_school}),
        )


def test_mapping_detects_drift_and_missing_school_entities(current):
    user, school = uuid4(), uuid4()
    command.downgrade(current.config, "0013")
    with current.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash,status,school_id) "
                "VALUES (:id,'scope@example.com','test-hash','LOCKED',:school)"
            ),
            {"id": user, "school": school},
        )
    command.upgrade(current.config, "head")
    with current.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT NOT convalidated FROM pg_constraint "
                "WHERE conname='fk_users_school_id_schools'"
            )
        )
    manifest = MappingManifest(schools={school: "Explicit School"})
    with current.factory() as session:
        plan = mapping_plan(session, manifest)
        assert plan["users"][0]["issues"] == ["SCHOOL_ENTITY_MISSING"]
    with current.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash) "
                "VALUES (:id,'unscoped@example.com','test-hash')"
            ),
            {"id": uuid4()},
        )
    with (
        pytest.raises(ValueError, match="data changed"),
        current.factory() as session,
        session.begin(),
    ):
        apply_mapping(session, manifest, approved_sha256=plan["plan_sha256"])
    assert counts(current.engine)["schools"] == 0
    with current.factory() as session, session.begin():
        new_plan = mapping_plan(session, manifest)
        apply_mapping(session, manifest, approved_sha256=new_plan["plan_sha256"])
    with current.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT status FROM core.users WHERE id=:id"), {"id": user})
            == "LOCKED"
        )
        assert connection.scalar(
            text(
                "SELECT convalidated FROM pg_constraint WHERE conname='fk_users_school_id_schools'"
            )
        )
    with pytest.raises(IntegrityError), current.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.users(id,email,password_hash,school_id) "
                "VALUES (:id,'orphan@example.com','test-hash',:school)"
            ),
            {"id": uuid4(), "school": uuid4()},
        )


def test_metadata_scope_single_head_and_empty_roundtrip(current):
    script = ScriptDirectory.from_config(current.config)
    assert len(script.get_heads()) == 1
    with current.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT convalidated FROM pg_constraint WHERE conname='fk_users_school_id_schools'"
            )
        )
    metadata = load_metadata()
    assert {name for tables in TABLES_INTRODUCED.values() for name in tables} == {
        table.name for table in metadata.tables.values()
    }
    assert all(table.schema == "core" for table in metadata.tables.values())
    assert all(
        fk.column.table.schema == "core"
        for table in metadata.tables.values()
        for fk in table.foreign_keys
    )
    with current.engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA unrelated_service"))
        connection.execute(text("CREATE TABLE unrelated_service.protected(id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO unrelated_service.protected VALUES (1)"))
    command.check(current.config)
    command.downgrade(current.config, "base")
    command.upgrade(current.config, "head")
    command.check(current.config)
    with current.engine.connect() as connection:
        assert connection.scalar(text("SELECT id FROM unrelated_service.protected")) == 1
        assert set(inspect(connection).get_table_names(schema="core")) == {
            t.name for t in metadata.tables.values()
        } | {"alembic_version"}


def test_outbox_report_shows_aggregate_counts_without_payload(monkeypatch):
    rows = [(1, True, 1), (1, False, 1), (2, True, 1), (2, False, 1), (3, True, 1)]

    class Result:
        def all(self):
            return rows

    class Session:
        def execute(self, _statement):
            return Result()

    monkeypatch.setattr(maintenance, "_head", lambda _session: None)
    report = maintenance.outbox_delivery_report(Session())

    assert report == {
        "total": 5,
        "by_schema_version": [
            {"schema_version": 1, "pending": 1, "published": 1},
            {"schema_version": 2, "pending": 1, "published": 1},
            {"schema_version": 3, "pending": 1, "published": 0},
        ],
    }
    serialized = json.dumps(report)
    assert "aggregate_id" not in serialized
    assert "payload_json" not in serialized


def test_actual_cli_seed_report_and_mapping_roundtrip(current, tmp_path):
    args = profile(current)
    environment = {
        **os.environ,
        "DATABASE_URL": current.engine.url.render_as_string(hide_password=False),
        "SECRET_KEY": "test-only-maintenance-signing-key-" + "x" * 32,
        "CORE_SEED_ADMIN_PASSWORD": args["admin_password"].get_secret_value(),
    }

    def invoke(*arguments, env=None):
        result = subprocess.run(
            [sys.executable, "-m", "app.maintenance", *arguments],
            env=env or environment,
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
        assert environment["CORE_SEED_ADMIN_PASSWORD"] not in result.stdout + result.stderr
        return result

    command_args = [
        "seed-dev",
        "--environment",
        "test",
        "--expected-database",
        current.name,
        "--school-id",
        str(args["school_id"]),
        "--school-name",
        args["school_name"],
    ]
    for created in (True, False):
        result = invoke(*command_args)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["created"] is created
    report = invoke("report")
    assert report.returncode == 0, report.stderr
    state = json.loads(report.stdout)
    pending = [user for user in state["users"] if "STUDENT_ACTIVATION_PENDING" in user["issues"]]
    assert len(pending) == 1
    manifest_file = tmp_path / "mapping.json"
    manifest_file.write_text(
        json.dumps({"schools": {str(args["school_id"]): args["school_name"]}}), encoding="utf-8"
    )
    planned = invoke("plan-school-mapping", "--manifest", str(manifest_file))
    assert planned.returncode == 0, planned.stderr
    applied = invoke(
        "apply-school-mapping",
        "--manifest",
        str(manifest_file),
        "--approved-sha256",
        json.loads(planned.stdout)["plan_sha256"],
    )
    assert applied.returncode == 0, applied.stderr
    assert (
        invoke(
            *command_args,
            env={
                key: value
                for key, value in environment.items()
                if key != "CORE_SEED_ADMIN_PASSWORD"
            },
        ).returncode
        == 1
    )
    with current.engine.begin() as connection:
        student_id = connection.scalar(
            text("SELECT id FROM core.users WHERE username='seed.student.1'")
        )
        connection.execute(
            text("UPDATE core.users SET school_id=NULL WHERE id=:id"), {"id": student_id}
        )
    other_school = uuid4()
    with pytest.raises(ValueError, match="Classroom history"), current.factory() as session:
        mapping_plan(
            session,
            MappingManifest(
                schools={other_school: "Wrong School"}, assignments={student_id: other_school}
            ),
        )


def test_report_detects_invalid_and_normalized_duplicate_usernames(current):
    with current.engine.begin() as connection:
        for username in ("same", " same", "bad@username"):
            connection.execute(
                text("INSERT INTO core.users(username,password_hash) VALUES (:name,'test-hash')"),
                {"name": username},
            )
    with current.factory() as session:
        report = mapping_plan(session, MappingManifest())
        assert sum("DUPLICATE_USERNAME" in user["issues"] for user in report["users"]) == 2
        assert sum("INVALID_USERNAME" in user["issues"] for user in report["users"]) == 2
        assert "bad@username" not in json.dumps(report)


def test_maintenance_requires_current_head(database):
    command.upgrade(database.config, "0004")
    with pytest.raises(ValueError, match="upgrade head"), database.factory() as session:
        mapping_plan(session, MappingManifest())
