"""60 concurrent TCP HTTP tasks against real PostgreSQL, local synthetic fixture."""

import json
import math
import platform
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.bootstrap import register_routers
from app.common.admission import DatabaseAdmissionMiddleware
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.outbox import OutboxEvent
from app.modules.notification.models import Notification
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.schemas import PostCreateRequest
from app.modules.social.feed.service import FeedService
from tests.vt034.conftest import headers


def test_tc14_load_60_large_updates(system, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("vt034-load-only-" + "x" * 32))
    posts = [
        FeedService(system.session).create_post(
            system.class_id, PostCreateRequest(body=f"original-{i}"), system.users["teacher"]
        )
        for i in range(60)
    ]
    with system.factory.begin() as db:
        db.execute(delete(Notification))
        db.execute(delete(OutboxEvent))
    app = FastAPI()
    app.add_middleware(DatabaseAdmissionMiddleware, capacity=14, timeout=3)
    register_error_handlers(app)
    register_routers(app)

    def database():
        with system.factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, loop="asyncio", lifespan="off", log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)  # readiness polling only, not a test oracle
        assert server.started
        auth = headers(system.users["teacher"])
        records = []
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            trust_env=False,
            timeout=10,
            limits=httpx.Limits(max_connections=60, max_keepalive_connections=60),
        ) as client:
            assert client.get("/health/live").status_code == 200
            for wave in range(3):
                barrier = threading.Barrier(60)
                body = str(wave) + "đ" * 9999  # exactly 10000 Unicode characters

                def task(index, barrier=barrier, body=body, wave=wave):
                    barrier.wait(timeout=15)
                    start = time.perf_counter()
                    response = client.patch(
                        f"/api/v1/classes/{system.class_id}/posts/{posts[index].id}",
                        headers=auth,
                        json={"body": body},
                    )
                    elapsed = time.perf_counter() - start
                    return {
                        "wave": wave,
                        "task": index,
                        "seconds": elapsed,
                        "status": response.status_code,
                        "body_matches": response.status_code == 200
                        and response.json()["body"] == body,
                    }

                with ThreadPoolExecutor(max_workers=60) as executor:
                    records.extend(executor.map(task, range(60)))
        with system.factory() as db:
            durable_events = db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "SOCIAL_POST_UPDATED")
            )
            inbox_count = db.scalar(select(func.count()).select_from(Notification))
            intact_posts = db.scalar(
                select(func.count())
                .select_from(ClassPost)
                .where(ClassPost.body == "2" + "đ" * 9999)
            )
        values = sorted(row["seconds"] for row in records)
        p95 = values[math.ceil(0.95 * len(values)) - 1]
        result = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "experiment": "local TCP HTTP + JWT + real PostgreSQL; same author, 60 distinct posts",
            "concurrency": 60,
            "waves": 3,
            "samples": len(values),
            "payload_characters": 10000,
            "postgresql": "16.2",
            "admission_capacity": 14,
            "fixture_pool": "5 + 10 overflow",
            "p95_method": "nearest rank, sorted[ceil(0.95*N)-1]",
            "p95_seconds": p95,
            "max_seconds": max(values),
            "target_seconds": 2.0,
            "within_target": p95 <= 2.0,
            "errors": sum(row["status"] != 200 for row in records),
            "durable_events": durable_events,
            "intact_posts": intact_posts,
            "inbox_count_worker_stopped": inbox_count,
            "limitations": [
                "3 finite waves, not sustained production load",
                "one author and class",
                "worker stopped; no inbox delivery-latency SLO",
                "no browser or remote network",
            ],
            "samples_detail": records,
        }
        output = Path(__file__).resolve().parents[4] / "docs/assignments/VT-034/evidence/load.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        assert all(row["body_matches"] for row in records)
        assert durable_events == 180 and intact_posts == 60 and inbox_count == 0
        assert p95 <= 2.0, f"Measured p95={p95:.3f}s exceeds VT-034 target"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
