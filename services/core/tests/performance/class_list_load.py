"""Standalone Core-06 probe, not a claim about unimplemented TP-01 services.

Run from services/core; TEST_DATABASE_URL must point to a dedicated test server.
Creates/drops its own sibling database. No existing application data is modified.
"""

import argparse
import asyncio
import hashlib
import json
import math
import multiprocessing
import os
import platform
import secrets
import threading
import time
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def percentile(values, p=0.95):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)] if ordered else None


async def sample_loop_lag(collecting, samples, interval=0.01):
    """Measure scheduler delay only for intervals wholly inside measurement."""
    while True:
        measured = collecting.is_set()
        began = time.perf_counter()
        await asyncio.sleep(interval)
        if measured and collecting.is_set():
            samples.append(max(0, time.perf_counter() - began - interval) * 1000)


def failure_reason(error):
    """Bounded labels only: exception messages may contain private request data."""
    if isinstance(error, httpx.RemoteProtocolError):
        if str(error) == "Server disconnected without sending a response.":
            return "server_disconnected_before_headers"
        if str(error).startswith("peer closed connection without sending complete message body"):
            return "incomplete_response_body"
        return "other_remote_protocol_error"
    return type(error).__name__


def ram_bytes():
    if os.name == "nt":
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                *[
                    (name, ctypes.c_ulonglong)
                    for name in (
                        "total",
                        "available",
                        "page_total",
                        "page_available",
                        "virtual_total",
                        "virtual_available",
                        "extended",
                    )
                ],
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
        return memory.total
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


class TimedApplication:
    """Collect server ingress-to-cleanup time without involving the load generator."""

    def __init__(self, app, collecting):
        self.app = app
        self.collecting = collecting
        self.timings = []
        self.loop_lag = []
        self.sampler = None

    async def __call__(self, scope, receive, send):
        if self.sampler is None:
            self.sampler = asyncio.create_task(sample_loop_lag(self.collecting, self.loop_lag))
        measured = (
            scope["type"] == "http"
            and scope["path"] == "/api/v1/classes"
            and self.collecting.is_set()
        )
        began = time.perf_counter()
        status = None

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            if measured:
                self.timings.append(((time.perf_counter() - began) * 1000, status))


def run_server(port, collecting, ready, stop, results):
    """Spawn target: import the real app/engine in its own interpreter and pool."""
    from app.common.db import engine
    from app.main import app

    measured = TimedApplication(app, collecting)
    server = uvicorn.Server(
        uvicorn.Config(
            measured,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            lifespan="off",
            ws="none",
        )
    )

    def observe_lifecycle():
        while not stop.wait(0.05):
            if server.started:
                ready.set()
        server.should_exit = True

    observer = threading.Thread(target=observe_lifecycle, daemon=True)
    observer.start()
    try:
        server.run()
        results.send(
            {"pid": os.getpid(), "timings": measured.timings, "loop_lag_ms": measured.loop_lag}
        )
    finally:
        stop.set()
        observer.join(timeout=1)
        engine.dispose()
        results.close()


def stop_server(process, stop, results, *, require_results=False):
    """Drain IPC before join: a large result must not deadlock the child pipe."""
    stop.set()
    received = None
    try:
        if require_results:
            if not results.poll(20):
                raise RuntimeError("Load server did not return measurement samples")
            received = results.recv()
        process.join(timeout=10)
        if process.is_alive():
            raise RuntimeError("Load server shutdown timed out")
        if require_results and process.exitcode != 0:
            raise RuntimeError("Load server exited unsuccessfully")
        return received
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        results.close()


def fixture(session):
    """Core integration fixture only; no usable password or onboarding endpoint.

    Identity owns these synthetic account rows; Classroom business state is built
    through its workflow. This process/database is disposable and never deployed.
    """
    from app.common.auth_dependencies import CurrentUser
    from app.modules.classroom.schemas import ClassCreateRequest, CourseCreateRequest
    from app.modules.classroom.service import ClassroomService
    from app.modules.identity.models import Role, RoleAssignment, User, UserStatus

    school, admin_id, teacher_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    students = []
    for user_id, role in [
        (admin_id, Role.ADMIN),
        (teacher_id, Role.LECTURER),
        *[(uuid4(), Role.STUDENT) for _ in range(500)],
    ]:
        session.add(
            User(
                id=user_id,
                school_id=school,
                status=UserStatus.ACTIVE,
                email=f"{user_id.hex}@example.com" if role != Role.STUDENT else None,
                username=f"load.{user_id.hex}" if role == Role.STUDENT else None,
                activated_at=now if role == Role.STUDENT else None,
                email_verified_at=now if role != Role.STUDENT else None,
                password_hash="unusable-fixture-" + secrets.token_hex(32),
            )
        )
        session.flush()
        session.add(RoleAssignment(user_id=user_id, role=role))
        if role == Role.STUDENT:
            students.append(user_id)
    session.commit()
    actor = CurrentUser(
        id=admin_id, school_id=school, status="ACTIVE", roles=["ADMIN"], session_version=1
    )
    classroom = ClassroomService(session)
    course = classroom.create_course(
        actor, CourseCreateRequest(code="LOAD", name="Synthetic load fixture")
    )
    users = []
    for index in range(10):
        klass = classroom.create_class(
            actor,
            ClassCreateRequest(
                name=f"Load class {index}",
                course_id=course.id,
                academic_year="2026-2027",
                semester="1",
                grade_level=9,
                enrollment_mode="MANUAL",
                primary_lecturer_id=teacher_id,
            ),
        )
        for student in students[index * 50 : (index + 1) * 50]:
            classroom.add_member(klass.id, actor, student, commit=False)
        session.commit()
        users.extend((student, klass.id) for student in students[index * 50 : index * 50 + 10])
    return users


async def exercise(clients, actors, duration, think_time):
    start = time.perf_counter()
    deadline = start + duration
    timings, statuses = [], {}
    errors, reasons = {}, {}
    wrong_scope = 0

    async def user(index, actor):
        nonlocal wrong_scope
        token, class_id = actor
        client = clients[index]
        await asyncio.sleep(index * think_time / len(actors))
        while time.perf_counter() < deadline:
            began = time.perf_counter()
            try:
                response = await client.get(
                    "/api/v1/classes", headers={"Authorization": "Bearer " + token}
                )
                status = response.status_code
                if status == 200:
                    items = response.json()["items"]
                    if len(items) != 1 or items[0]["id"] != class_id:
                        wrong_scope += 1
                        status = "scope_mismatch"
            except (httpx.HTTPError, ValueError, KeyError) as error:
                status = "transport_or_contract_error"
                category = type(error).__name__
                errors[category] = errors.get(category, 0) + 1
                reason = failure_reason(error)
                reasons[reason] = reasons.get(reason, 0) + 1
            elapsed = time.perf_counter() - began
            timings.append(elapsed * 1000)
            statuses[str(status)] = statuses.get(str(status), 0) + 1
            await asyncio.sleep(max(0, think_time - elapsed))

    await asyncio.gather(*(user(index, actor) for index, actor in enumerate(actors)))
    return timings, statuses, wrong_scope, time.perf_counter() - start, errors, reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=600)
    parser.add_argument("--warmup-seconds", type=int, default=30)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--think-seconds", type=float, default=1)
    parser.add_argument("--port", type=int, default=28515)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not 1 <= args.users <= 100
        or args.duration_seconds < 1
        or args.warmup_seconds < 0
        or args.think_seconds < 0
    ):
        parser.error("Invalid load parameters")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error(
            "Set TEST_DATABASE_URL to a dedicated disposable PostgreSQL server with CREATEDB"
        )
    name = "test_core_load_" + uuid4().hex
    parent = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    database_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    # Set environment before importing application composition or database modules.
    os.environ["DATABASE_URL"] = database_url
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    import app
    from app.common.config import settings

    settings.database_url = database_url
    settings.secret_key = SecretStr(os.environ["SECRET_KEY"])
    from app.common.db import engine
    from app.common.security import create_access_token

    # Spawn on every OS: no inherited engine/pooled connections and no shared GIL.
    context = multiprocessing.get_context("spawn")
    collecting, ready, stop = context.Event(), context.Event(), context.Event()
    result_reader, result_writer = context.Pipe(duplex=False)
    server_process = None

    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        with Session(engine, autoflush=False) as session:
            users = fixture(session)
        actors = [
            (create_access_token(user_id, ["STUDENT"], 1), str(class_id))
            for user_id, class_id in users[: args.users]
        ]
        with engine.connect() as connection:
            database_version = connection.scalar(text("SHOW server_version"))
            revision = connection.scalar(text("SELECT version_num FROM core.alembic_version"))
        server_process = context.Process(
            target=run_server,
            args=(args.port, collecting, ready, stop, result_writer),
            name="core-load-server",
        )
        server_process.start()
        result_writer.close()
        for _ in range(300):
            if ready.wait(0.1):
                break
            if not server_process.is_alive():
                raise RuntimeError("Load server failed to start")
        if not ready.is_set():
            raise RuntimeError("Load server startup timed out")
        base_url = f"http://127.0.0.1:{args.port}"
        print(
            f"Core-06: warmup {args.warmup_seconds}s, {args.users} users; 10 classes / 500 synthetic students",
            flush=True,
        )

        client_loop_lag = []

        async def measure():
            # Each independent user retains its own connection, as independent
            # browser sessions would, through both warmup and measurement. A
            # shared HTTPX queue can serialize unrelated synthetic users.
            async with AsyncExitStack() as stack:
                clients = [
                    await stack.enter_async_context(
                        httpx.AsyncClient(
                            base_url=base_url,
                            timeout=15,
                            trust_env=False,
                            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
                        )
                    )
                    for _ in actors
                ]
                sampler = asyncio.create_task(sample_loop_lag(collecting, client_loop_lag))
                try:
                    await exercise(clients, actors, args.warmup_seconds, args.think_seconds)
                    collecting.set()
                    print(f"Core-06: measuring for {args.duration_seconds}s", flush=True)
                    return await exercise(
                        clients, actors, args.duration_seconds, args.think_seconds
                    )
                finally:
                    collecting.clear()
                    sampler.cancel()
                    with suppress(asyncio.CancelledError):
                        await sampler

        timings, statuses, wrong_scope, elapsed, errors, reasons = asyncio.run(measure())
        server_result = stop_server(server_process, stop, result_reader, require_results=True)
        backend_timings = server_result["timings"]
        if server_result["pid"] == os.getpid():
            raise RuntimeError("Load server must use a separate process")
        total = len(timings)
        success = statuses.get("200", 0) / total if total else 0
        backend_p95 = percentile([latency for latency, _ in backend_timings])
        report = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "scope": "Core class-list HTTP API only; TP-01 Core subset, not full mixed-service TP-01",
            "pending_services": [
                "Document fixtures (20 x 10 MB/class)",
                "Learning (30 questions/assessment)",
                "AI",
                "Learner Intelligence",
            ],
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "application_sha256": hashlib.sha256(
                b"".join(
                    path.read_bytes() for path in sorted(Path(app.__file__).parent.rglob("*.py"))
                )
            ).hexdigest(),
            "environment": {
                "os": platform.system(),
                "cpu": platform.processor(),
                "logical_cpus": os.cpu_count(),
                "ram_bytes": ram_bytes(),
                "python": platform.python_version(),
                "packages": {
                    name: version(name)
                    for name in ("fastapi", "starlette", "httpx", "httpcore", "anyio", "uvicorn")
                },
                "load_runtime": os.environ.get("CORE_LOAD_RUNTIME", "caller-provided"),
                "application_artifact": (
                    "installed-package" if "site-packages" in app.__file__ else "source-tree"
                ),
                "postgresql": database_version,
                "migration": revision,
                "http": "Uvicorn one worker, loopback HTTP",
                "process_isolation": "spawned server; separate interpreter/GIL and DB pool",
                "server_pid": server_result["pid"],
                "load_generator_pid": os.getpid(),
                "database": "Dedicated disposable PostgreSQL; route supplied by test environment",
                "pool_size": engine.pool.size(),
                "max_overflow": settings.database_max_overflow,
                "queue_broker": "none; Core transactional outbox",
                "ai_model": "not involved",
                "region": "local",
                "background_activity": "Shared development host; no CPU/RAM reservation",
            },
            "load": {
                "users": args.users,
                "classes": 10,
                "students_per_class": 50,
                "warmup_seconds": args.warmup_seconds,
                "configured_seconds": args.duration_seconds,
                "elapsed_seconds": elapsed,
                "think_seconds": args.think_seconds,
                "schedule": "closed-loop users, evenly staggered within one think interval; one persistent HTTP client/pool per user through warmup/measurement",
            },
            "requests": total,
            "status_counts": statuses,
            "client_error_counts": errors,
            "client_error_reasons": reasons,
            "event_loop_lag": {
                "sample_interval_ms": 10,
                "client_samples": len(client_loop_lag),
                "client_p95_ms": percentile(client_loop_lag),
                "client_max_ms": max(client_loop_lag, default=0),
                "server_samples": len(server_result["loop_lag_ms"]),
                "server_p95_ms": percentile(server_result["loop_lag_ms"]),
                "server_max_ms": max(server_result["loop_lag_ms"], default=0),
            },
            "success_ratio": success,
            "backend_samples": len(backend_timings),
            "backend_p95_ms": backend_p95,
            "client_p95_ms": percentile(timings),
            "client_max_ms": max(timings, default=0),
            "wrong_scope_responses": wrong_scope,
            "passed_core_thresholds": backend_p95 is not None
            and backend_p95 <= 500
            and success >= 0.99
            and wrong_scope == 0,
            "full_tp01_verified": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "requests",
                        "backend_p95_ms",
                        "client_p95_ms",
                        "success_ratio",
                        "wrong_scope_responses",
                        "passed_core_thresholds",
                    )
                }
            ),
            flush=True,
        )
        return 0 if report["passed_core_thresholds"] else 1
    finally:
        if server_process is not None and server_process.is_alive():
            stop_server(server_process, stop, result_reader)
        else:
            result_reader.close()
        result_writer.close()
        engine.dispose()
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
