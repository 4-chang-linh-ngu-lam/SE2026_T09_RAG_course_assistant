"""VT-033 real loopback HTTP / PostgreSQL probe; run from services/core.

Requires TEST_DATABASE_URL on a dedicated disposable PostgreSQL 16 server. Only
the newly generated sibling database is migrated/seeded/dropped. No tokens/DSNs
are written to the aggregate report. Existing application data is never touched.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from class_list_load import percentile, ram_bytes
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def fixture(engine, count, page_size):
    # This is isolated test seeding, not a production cross-module interface.
    from app.common.pagination import encode_cursor
    from app.common.security import create_access_token
    from app.modules.classroom.models import School
    from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
    from app.modules.notification.models import Notification

    total = page_size + 3
    with Session(engine) as session:
        school = School(name="VT033 synthetic load school")
        session.add(school)
        session.flush()
        users = [
            User(
                id=uuid4(),
                school_id=school.id,
                username="vt033." + uuid4().hex,
                password_hash="unusable-fixture-" + secrets.token_hex(32),
                status=UserStatus.ACTIVE,
                activated_at=datetime.now(UTC),
            )
            for _ in range(count)
        ]
        session.add_all(users)
        session.flush()
        for user in users:
            session.add(RoleAssignment(user_id=user.id, role=Role.STUDENT))
            session.add_all(
                Notification(
                    id=uuid4(),
                    recipient_id=user.id,
                    type="CLASS_STATUS_CHANGED",
                    payload_json={"version": i + 1},
                    dedup_key=uuid4().hex,
                    read_at=datetime.now(UTC) if i == 0 else None,
                )
                for i in range(total)
            )
        session.commit()
        actors = []
        for user in users:
            rows = list(
                session.scalars(
                    select(Notification)
                    .where(Notification.recipient_id == user.id)
                    .order_by(Notification.sequence.desc())
                )
            )
            actors.append(
                {
                    "token": create_access_token(user.id, ["STUDENT"], 1),
                    "ids": [str(row.id) for row in rows[:page_size]],
                    "payloads": [row.payload_json for row in rows[:page_size]],
                    "cursor": encode_cursor(rows[page_size - 1].id),
                    "unread": total - 1,
                }
            )
    return actors, total


async def exercise(client, actors, duration):
    go = asyncio.Event()
    timings, statuses = [], {}
    in_flight = peak = mismatches = timeouts = transport_errors = 0
    start = deadline = 0

    async def actor_loop(actor):
        nonlocal in_flight, peak, mismatches, timeouts, transport_errors
        await go.wait()
        while time.perf_counter() < deadline:
            began = time.perf_counter()
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                response = await client.get(
                    "/api/v1/notifications",
                    headers={"Authorization": "Bearer " + actor["token"]},
                )
                status = str(response.status_code)
                if response.status_code == 200:
                    body = response.json()
                    valid = (
                        set(body) == {"items", "unread_count", "next_cursor"}
                        and [item["id"] for item in body["items"]] == actor["ids"]
                        and [item["payload_json"] for item in body["items"]] == actor["payloads"]
                        and all(item["read"] is False for item in body["items"])
                        and body["unread_count"] == actor["unread"]
                        and body["next_cursor"] == actor["cursor"]
                        and response.headers.get("Cache-Control") == "no-store"
                    )
                    if not valid:
                        mismatches += 1
            except httpx.TimeoutException:
                timeouts += 1
                status = "timeout"
            except httpx.HTTPError:
                transport_errors += 1
                status = "transport_error"
            except (KeyError, TypeError, ValueError):
                mismatches += 1
                status = "invalid_contract"
            finally:
                in_flight -= 1
                timings.append((time.perf_counter() - began) * 1000)
            statuses[status] = statuses.get(status, 0) + 1

    tasks = [asyncio.create_task(actor_loop(actor)) for actor in actors]
    await asyncio.sleep(0)  # all tasks reach the same barrier before release
    start = time.perf_counter()
    deadline = start + duration
    go.set()
    await asyncio.gather(*tasks)
    return {
        "timings": timings,
        "status_counts": statuses,
        "actual_tasks": len(tasks),
        "peak_client_in_flight": peak,
        "content_or_ownership_errors": mismatches,
        "timeouts": timeouts,
        "transport_errors": transport_errors,
        "elapsed_seconds": time.perf_counter() - start,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=120)
    parser.add_argument("--page-size", type=int, default=2)
    parser.add_argument("--warmup-seconds", type=int, default=30)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (1 <= args.users <= 120 and 1 <= args.page_size <= 100):
        parser.error("users must be 1..120 and page-size 1..100")
    if args.duration_seconds < 1 or args.warmup_seconds < 0:
        parser.error("duration must be positive and warmup nonnegative")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("Set TEST_DATABASE_URL to a dedicated PostgreSQL 16 test server")
    name = "vt033_load_" + uuid4().hex
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with parent.connect() as connection:
        version = connection.scalar(text("SHOW server_version"))
        if int(version.split(".")[0]) != 16:
            raise SystemExit("PostgreSQL 16 required")
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    database_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = database_url
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    os.environ["NOTIFICATION_PAGE_SIZE_DEFAULT"] = str(args.page_size)
    server = thread = engine = None
    backend_timings = []
    collecting = False

    try:
        # Import only after setting the process environment; no dependency overrides.
        from app.common.config import settings
        from app.common.db import engine
        from app.main import app

        assert settings.notification_page_size_default == args.page_size
        command.upgrade(Config("alembic.ini"), "head")
        actors, rows_per_actor = fixture(engine, args.users, args.page_size)

        class TimedApplication:
            async def __call__(self, scope, receive, send):
                measured = collecting and scope["type"] == "http"
                began = time.perf_counter()
                try:
                    await app(scope, receive, send)
                finally:
                    if measured:
                        backend_timings.append((time.perf_counter() - began) * 1000)

        # Bind once and pass this socket to Uvicorn, avoiding a port-selection race.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(
                uvicorn.Config(
                    TimedApplication(),
                    log_level="error",
                    access_log=False,
                    lifespan="off",
                    ws="none",
                )
            )
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError("Local HTTP server failed to start")
                time.sleep(0.1)
            if not server.started:
                raise RuntimeError("Local HTTP server startup timed out")

            async def measure():
                nonlocal collecting
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    trust_env=False,
                    timeout=15,
                    limits=httpx.Limits(
                        max_connections=args.users, max_keepalive_connections=args.users
                    ),
                ) as client:
                    print(f"warmup: {args.users} actors / {args.warmup_seconds}s", flush=True)
                    warmup = await exercise(client, actors, args.warmup_seconds)
                    collecting = True
                    print(f"measure: {args.users} actors / {args.duration_seconds}s", flush=True)
                    cpu_start = time.process_time()
                    try:
                        result = await exercise(client, actors, args.duration_seconds)
                    finally:
                        collecting = False
                    result["process_cpu_seconds"] = time.process_time() - cpu_start
                    result["warmup_requests"] = len(warmup["timings"])
                    result["warmup_errors"] = (
                        len(warmup["timings"])
                        - warmup["status_counts"].get("200", 0)
                        + warmup["content_or_ownership_errors"]
                    )
                    return result

            measured = asyncio.run(measure())
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("HTTP server did not stop before database cleanup")

        timings = measured.pop("timings")
        total = len(timings)
        errors = total - measured["status_counts"].get("200", 0)
        p95 = percentile(timings)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        report = {
            "run_id": uuid4().hex,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "scope": "VT-033 Notification list only, real Identity/HTTP/PostgreSQL",
            "baseline_sha": "9ee864c3404f8057b394592791404f6db8692826",
            "patch_sha": sha,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "application_sha256": hashlib.sha256(
                b"".join(p.read_bytes() for p in sorted(Path("app").rglob("*.py")))
            ).hexdigest(),
            "environment": {
                "os": platform.platform(),
                "cpu": platform.processor(),
                "logical_cpus": os.cpu_count(),
                "ram_bytes": ram_bytes(),
                "python": platform.python_version(),
                "postgresql": version,
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
                "admission_capacity": max(
                    1, settings.database_pool_size + settings.database_max_overflow - 1
                ),
                "http": "one Uvicorn worker, client/server same Windows process, loopback",
                "database": "dedicated PostgreSQL16 Docker, generated sibling DB",
                "background_activity": "Shared workstation and Docker/WSL; no CPU/RAM isolation",
            },
            "load": {
                "configured_actors": args.users,
                "page_size": args.page_size,
                "rows_per_actor": rows_per_actor,
                "warmup_seconds": args.warmup_seconds,
                "configured_seconds": args.duration_seconds,
                "schedule": "closed-loop, zero think time, shared start barrier, no fixed arrival rate",
            },
            **measured,
            "requests": total,
            "errors": errors,
            "error_rate": errors / total if total else 1,
            "client_p50_ms": percentile(timings, 0.50),
            "client_p95_ms": p95,
            "client_p99_ms": percentile(timings, 0.99),
            "client_max_ms": max(timings, default=0),
            "backend_samples": len(backend_timings),
            "backend_p50_ms": percentile(backend_timings, 0.50),
            "backend_p95_ms": percentile(backend_timings),
            "backend_p99_ms": percentile(backend_timings, 0.99),
            "backend_max_ms": max(backend_timings, default=0),
            "client_p95_target_ms": 3500,
            "passed_vt033": bool(
                args.users == 120
                and measured["peak_client_in_flight"] == 120
                and args.duration_seconds >= 180
                and args.warmup_seconds >= 30
                and p95 is not None
                and p95 <= 3500
                and errors == 0
                and measured["content_or_ownership_errors"] == 0
                and measured["warmup_errors"] == 0
            ),
            "limitations": "Finite local read-only workload; no browser, write mix, external AI or production capacity certification. Backend admission intentionally executes fewer requests than client in-flight.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "requests",
                        "errors",
                        "content_or_ownership_errors",
                        "client_p95_ms",
                        "peak_client_in_flight",
                        "passed_vt033",
                    )
                }
            ),
            flush=True,
        )
        return 0 if report["passed_vt033"] else 1
    finally:
        if server:
            server.should_exit = True
        if thread and thread.is_alive():
            thread.join(timeout=20)
        if engine:
            engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
