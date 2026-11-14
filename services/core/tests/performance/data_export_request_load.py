"""Measure VT-035 request-only export intake under concurrent authenticated load.

Run from services/core with TEST_DATABASE_URL pointing to a disposable PostgreSQL
server/account with CREATEDB. The runner creates and drops a sibling test database.
This measures request creation, not file generation or secure out-of-band delivery.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import secrets
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def percentile(values: list[float], p: float = 0.95) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, int(len(ordered) * p + 0.999999) - 1)]


def seed_users(session: Session, count: int) -> list[object]:
    from app.modules.classroom.models import School
    from app.modules.identity.models import (
        Role,
        RoleAssignment,
        User,
        UserStatus,
    )

    school_id = uuid4()
    now = datetime.now(UTC)
    session.add(School(id=school_id, name="VT-035 synthetic export school"))
    session.flush()
    actors = []
    for index in range(count):
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                school_id=school_id,
                email=None,
                username=f"export.{index:03d}.{user_id.hex[:8]}",
                display_name=f"Synthetic student {index:03d}",
                status=UserStatus.ACTIVE,
                activated_at=now,
                password_hash="unusable-fixture-" + secrets.token_hex(24),
            )
        )
        session.flush()
        session.add(RoleAssignment(user_id=user_id, role=Role.STUDENT))
        actors.append(user_id)
    session.commit()
    return actors


async def run_round(
    client,
    actors,
    round_number,
    idempotency_key_per_request,
    client_latencies,
    status_counts,
    scope_mismatches,
    contract_errors,
    transport_errors,
    response_errors,
    response_error_codes,
    created_ids,
):
    async def fetch(actor):
        user_id, token = actor
        started = time.perf_counter()
        try:
            headers = {"Authorization": f"Bearer {token}"}
            if idempotency_key_per_request:
                headers["Idempotency-Key"] = str(uuid4())
            response = await client.post(
                "/api/v1/users/me/data-export",
                headers=headers,
                json={"reason": f"VT035-load-{user_id.hex}-{round_number}"},
            )
            status = str(response.status_code)
            status_counts[status] = status_counts.get(status, 0) + 1
            if response.status_code != 201:
                response_errors[status] = response_errors.get(status, 0) + 1
                try:
                    code = response.json().get("error", {}).get("code", "MISSING_CODE")
                except (TypeError, ValueError):
                    code = "INVALID_ERROR_BODY"
                response_error_codes[code] = response_error_codes.get(code, 0) + 1
                client_latencies.append((time.perf_counter() - started) * 1000)
                return
            if "content-disposition" in response.headers:
                contract_errors[0] += 1
            payload = response.json()
            allowed_fields = {
                "id",
                "user_id",
                "type",
                "reason",
                "status",
                "resolution_note",
                "created_at",
                "updated_at",
            }
            if set(payload) != allowed_fields:
                contract_errors[0] += 1
            if payload.get("user_id") != str(user_id):
                scope_mismatches[0] += 1
            expected_reason = f"VT035-load-{user_id.hex}-{round_number}"
            if (
                payload.get("type") != "EXPORT"
                or payload.get("status") != "PENDING"
                or payload.get("reason") != expected_reason
            ):
                contract_errors[0] += 1
            if isinstance(payload.get("id"), str):
                created_ids.setdefault(str(user_id), set()).add(payload["id"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            status_counts["transport_or_contract_error"] = (
                status_counts.get("transport_or_contract_error", 0) + 1
            )
            transport_errors[0] += 1
        client_latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(fetch(actor) for actor in actors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=150)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument(
        "--idempotency-key-per-request",
        action="store_true",
        help="Diagnostic: use a fresh key per intent to measure bounded retry-cache capacity",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.users <= 150 or args.rounds < 1:
        parser.error("Use 1–150 users and at least one round")
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        parser.error("Set TEST_DATABASE_URL to a disposable PostgreSQL server with CREATEDB")

    database_name = "test_data_export_" + uuid4().hex
    parent = create_engine(base_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    created_database = False
    app_engine = None
    server = None
    thread = None
    try:
        with parent.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created_database = True
        database_url = (
            make_url(base_url).set(database=database_name).render_as_string(hide_password=False)
        )
        secret_key = secrets.token_urlsafe(48)
        os.environ["DATABASE_URL"] = database_url
        os.environ["SECRET_KEY"] = secret_key

        from app.common.config import settings

        settings.database_url = database_url
        settings.secret_key = SecretStr(secret_key)
        from app.common.db import engine as app_engine
        from app.common.security import create_access_token
        from app.main import app

        migration_config = Config("alembic.ini")
        command.upgrade(migration_config, "head")
        with Session(app_engine, autoflush=False) as session:
            seeded = seed_users(session, args.users)
        actors = [(user_id, create_access_token(user_id, ["STUDENT"], 1)) for user_id in seeded]
        with app_engine.connect() as connection:
            postgres_version = connection.scalar(text("SHOW server_version"))
            migration = connection.scalar(text("SELECT version_num FROM core.alembic_version"))

        backend_samples: list[tuple[float, int | None]] = []
        collecting = False

        class TimedApplication:
            async def __call__(self, scope, receive, send):
                started = time.perf_counter()
                status = None

                async def timed_send(message):
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                    await send(message)

                try:
                    await app(scope, receive, timed_send)
                finally:
                    if (
                        collecting
                        and scope["type"] == "http"
                        and scope["method"] == "POST"
                        and scope["path"] == "/api/v1/users/me/data-export"
                    ):
                        backend_samples.append(((time.perf_counter() - started) * 1000, status))

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                TimedApplication(),
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                lifespan="off",
                ws="none",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Load server failed to start")
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("Load server startup timed out")

        client_latencies: list[float] = []
        status_counts: dict[str, int] = {}
        scope_mismatches = [0]
        contract_errors = [0]
        transport_errors = [0]
        response_errors: dict[str, int] = {}
        response_error_codes: dict[str, int] = {}
        measured_created_ids: dict[str, set[str]] = {}
        warmup_created_ids: dict[str, set[str]] = {}
        warmup_statuses: dict[str, int] = {}
        warmup_scope_mismatches = [0]
        warmup_contract_errors = [0]
        warmup_transport_errors = [0]
        warmup_response_errors: dict[str, int] = {}
        warmup_response_error_codes: dict[str, int] = {}

        async def measure():
            nonlocal collecting
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}",
                timeout=20,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=args.users,
                    max_keepalive_connections=args.users,
                ),
            ) as client:
                await run_round(
                    client,
                    actors,
                    "warmup",
                    args.idempotency_key_per_request,
                    [],
                    warmup_statuses,
                    warmup_scope_mismatches,
                    warmup_contract_errors,
                    warmup_transport_errors,
                    warmup_response_errors,
                    warmup_response_error_codes,
                    warmup_created_ids,
                )
                collecting = True
                for round_number in range(args.rounds):
                    await run_round(
                        client,
                        actors,
                        round_number,
                        args.idempotency_key_per_request,
                        client_latencies,
                        status_counts,
                        scope_mismatches,
                        contract_errors,
                        transport_errors,
                        response_errors,
                        response_error_codes,
                        measured_created_ids,
                    )
                collecting = False

        asyncio.run(measure())
        from app.modules.identity.models import DataRequest, DataRequestType

        user_ids = [user_id for user_id, _ in actors]
        expected_ids = {
            user_id: measured_created_ids.get(str(user_id), set())
            | warmup_created_ids.get(str(user_id), set())
            for user_id in user_ids
        }
        actual_ids: dict[object, set[str]] = {user_id: set() for user_id in user_ids}
        with Session(app_engine, autoflush=False) as session:
            rows = session.scalars(
                select(DataRequest).where(
                    DataRequest.user_id.in_(user_ids),
                    DataRequest.request_type == DataRequestType.EXPORT,
                )
            )
            for row in rows:
                actual_ids[row.user_id].add(str(row.id))
        database_mismatches = sum(
            actual_ids[user_id] != expected_ids[user_id] for user_id in user_ids
        )
        total = len(client_latencies)
        success = status_counts.get("201", 0) / total if total else 0
        client_p95 = percentile(client_latencies)
        client_p99 = percentile(client_latencies, 0.99)
        client_max = max(client_latencies, default=None)
        app_latencies = [sample[0] for sample in backend_samples]
        app_p95 = percentile(app_latencies)
        app_p99 = percentile(app_latencies, 0.99)
        app_max = max(app_latencies, default=None)
        warmup_passed = (
            warmup_statuses.get("201", 0) == args.users
            and warmup_scope_mismatches[0] == 0
            and warmup_contract_errors[0] == 0
            and warmup_transport_errors[0] == 0
            and not warmup_response_errors
            and not warmup_response_error_codes
        )
        report = {
            "scope": "Authenticated POST /users/me/data-export request creation only; no data file is generated or delivered",
            "policy": "Admin identity verification and approved manual handoff remain required by the current contract",
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "users": args.users,
            "rounds": args.rounds,
            "warmup_rounds": 1,
            "concurrent_requests_per_round": args.users,
            "requests": total,
            "synthetic_export_requests_per_user": args.rounds,
            "postgresql_version": postgres_version,
            "migration": migration,
            "python": platform.python_version(),
            "worker_count": 1,
            "database_pool_size": settings.database_pool_size,
            "database_max_overflow": settings.database_max_overflow,
            "database_pool_timeout_seconds": settings.database_pool_timeout_seconds,
            "auth_idempotency_max_keys": settings.auth_idempotency_max_keys,
            "idempotency_key_used": args.idempotency_key_per_request,
            "warmup_passed": warmup_passed,
            "status_counts": status_counts,
            "success_ratio": success,
            "scope_or_contract_mismatches": scope_mismatches[0],
            "contract_errors": contract_errors[0],
            "transport_errors": transport_errors[0],
            "non_201_responses": response_errors,
            "non_201_error_codes": response_error_codes,
            "warmup_non_201_error_codes": warmup_response_error_codes,
            "client_p95_ms": client_p95,
            "client_p99_ms": client_p99,
            "client_max_ms": client_max,
            "app_p95_ms": app_p95,
            "app_p99_ms": app_p99,
            "app_max_ms": app_max,
            "database_persisted_scope_mismatches": database_mismatches,
            "target_p95_ms": 4000,
            "passed": total == args.users * args.rounds
            and status_counts.get("201", 0) == total
            and warmup_passed
            and scope_mismatches[0] == 0
            and contract_errors[0] == 0
            and transport_errors[0] == 0
            and database_mismatches == 0
            and client_p95 is not None
            and client_p95 <= 4000,
            "limitations": [
                "Measures request intake only; not file generation, secure handoff or cross-service export",
                "Local loopback and PostgreSQL version above; not production or CI capacity evidence",
                "150 concurrent requests are launched in synchronized rounds; no external network delay",
            ],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        if app_engine is not None:
            app_engine.dispose()
        if created_database:
            with parent.connect() as connection:
                connection.exec_driver_sql(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (database_name,),
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        parent.dispose()


if __name__ == "__main__":
    main()
