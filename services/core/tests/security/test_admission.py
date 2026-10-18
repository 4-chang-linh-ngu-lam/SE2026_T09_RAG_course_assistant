import asyncio
import json

import pytest

from app.common.admission import DatabaseAdmissionMiddleware


def test_admission_bounds_concurrent_work_and_releases_after_error_and_cancel():
    async def scenario():
        active, maximum = 0, 0
        entered = asyncio.Event()
        release = asyncio.Event()

        async def app(scope, receive, send):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            try:
                if scope["path"] == "/api/cancel":
                    entered.set()
                    await release.wait()
                elif scope["path"] == "/api/error":
                    raise RuntimeError("synthetic")
                else:
                    await asyncio.sleep(0.001)
            finally:
                active -= 1

        async def unused(*args):
            pass

        gate = DatabaseAdmissionMiddleware(app, capacity=2, timeout=1)

        async def request(path):
            await gate({"type": "http", "path": path}, unused, unused)

        await asyncio.gather(*(request("/api/work") for _ in range(100)))
        assert maximum == 2 and active == 0
        with pytest.raises(RuntimeError):
            await request("/api/error")
        task = asyncio.create_task(request("/api/cancel"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(request("/api/work"), request("/api/work"))
        assert active == 0

    asyncio.run(scenario())


def test_admission_overload_is_safe_503_and_liveness_bypasses_queue():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def app(scope, receive, send):
            if scope["path"].startswith("/api/"):
                entered.set()
                await release.wait()
            else:
                await send({"type": "http.response.start", "status": 200, "headers": []})

        async def unused(*args):
            pass

        gate = DatabaseAdmissionMiddleware(app, capacity=1, timeout=0.01)
        messages = []

        async def capture(message):
            messages.append(message)

        first = asyncio.create_task(gate({"type": "http", "path": "/api/work"}, unused, unused))
        await entered.wait()
        await gate({"type": "http", "path": "/health/live"}, unused, capture)
        assert messages.pop()["status"] == 200
        await gate(
            {
                "type": "http",
                "path": "/api/work",
                "headers": [],
                "state": {"correlation_id": "synthetic-id"},
            },
            unused,
            capture,
        )
        assert messages[0]["status"] == 503
        body = json.loads(messages[1]["body"])
        assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert body["error"]["correlation_id"] == "synthetic-id"
        assert dict(messages[0]["headers"])[b"cache-control"] == b"no-store"
        release.set()
        await first

    asyncio.run(scenario())
