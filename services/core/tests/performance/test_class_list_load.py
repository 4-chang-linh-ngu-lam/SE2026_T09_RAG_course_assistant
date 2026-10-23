import asyncio
import json
import threading
from contextlib import suppress

import httpx
import pytest
from class_list_load import TimedApplication, exercise, sample_loop_lag, stop_server


def test_server_timing_tracks_ingress_through_cleanup_across_measurement_boundary():
    collecting = threading.Event()
    collecting.set()
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"{}"})
        # HTTPX can finish reading before dependency cleanup completes. The sample
        # still belongs to the measured request even when collection ends here.
        collecting.clear()
        await asyncio.sleep(0.005)

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    measured = TimedApplication(app, collecting)
    asyncio.run(measured({"type": "http", "path": "/api/v1/classes"}, receive, send))
    assert sent[-1]["type"] == "http.response.body"
    assert len(measured.timings) == 1
    duration, status = measured.timings[0]
    assert duration >= 5
    assert status == 200


@pytest.mark.parametrize("path,enabled", [("/health/ready", True), ("/api/v1/classes", False)])
def test_warmup_and_other_routes_are_excluded_from_backend_samples(path, enabled):
    collecting = threading.Event()
    if enabled:
        collecting.set()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 503})

    async def ignored(*args):
        pass

    measured = TimedApplication(app, collecting)
    asyncio.run(measured({"type": "http", "path": path}, ignored, ignored))
    assert measured.timings == []


def test_raised_request_still_contributes_backend_time_without_fabricated_success():
    collecting = threading.Event()
    collecting.set()

    async def app(scope, receive, send):
        raise RuntimeError("synthetic failure")

    measured = TimedApplication(app, collecting)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        asyncio.run(measured({"type": "http", "path": "/api/v1/classes"}, None, None))
    assert len(measured.timings) == 1
    assert measured.timings[0][1] is None


def test_server_results_are_drained_before_join_and_timed_out_child_is_terminated():
    sequence = []

    class Process:
        exitcode = 0
        running = True

        def join(self, timeout):
            sequence.append("join")

        def is_alive(self):
            return self.running

        def terminate(self):
            sequence.append("terminate")
            self.running = False

    class Results:
        def poll(self, timeout):
            return True

        def recv(self):
            sequence.append("receive")
            return {"pid": 42, "timings": [(4, 200)]}

        def close(self):
            sequence.append("close")

    stop = threading.Event()
    with pytest.raises(RuntimeError, match="shutdown timed out"):
        stop_server(Process(), stop, Results(), require_results=True)
    assert stop.is_set()
    assert sequence == ["receive", "join", "terminate", "join", "close"]


def test_independent_users_keep_their_own_client_and_validate_their_own_class():
    seen = [0, 0]

    class Response:
        status_code = 200

        def __init__(self, class_id):
            self.class_id = class_id

        def json(self):
            return {"items": [{"id": self.class_id}]}

    class Client:
        def __init__(self, index):
            self.index = index

        async def get(self, path, headers):
            assert path == "/api/v1/classes"
            assert headers["Authorization"] == f"Bearer synthetic-{self.index}"
            seen[self.index] += 1
            await asyncio.sleep(0.001)
            return Response(f"class-{self.index}")

    timings, statuses, wrong_scope, elapsed, errors, reasons = asyncio.run(
        exercise(
            [Client(0), Client(1)],
            [("synthetic-0", "class-0"), ("synthetic-1", "class-1")],
            duration=0.02,
            think_time=0,
        )
    )
    assert all(count > 0 for count in seen)
    assert statuses == {"200": len(timings)}
    assert wrong_scope == 0
    assert errors == {}
    assert reasons == {}
    assert elapsed >= 0.02


def test_transport_failures_are_counted_without_retry_or_private_exception_text():
    class Client:
        calls = 0

        async def get(self, *args, **kwargs):
            self.calls += 1
            raise httpx.RemoteProtocolError("private synthetic token in an unexpected message")

    client = Client()
    timings, statuses, wrong_scope, _, errors, reasons = asyncio.run(
        exercise([client], [("synthetic", "class")], duration=0.02, think_time=0.05)
    )
    assert client.calls == len(timings) == 1
    assert statuses == {"transport_or_contract_error": 1}
    assert wrong_scope == 0
    assert errors == {"RemoteProtocolError": 1}
    assert reasons == {"other_remote_protocol_error": 1}
    assert "private" not in json.dumps([statuses, errors, reasons])


def test_loop_lag_excludes_warmup_and_stops_cleanly():
    async def measure():
        collecting, samples = threading.Event(), []
        sampler = asyncio.create_task(sample_loop_lag(collecting, samples, interval=0.001))
        await asyncio.sleep(0.01)
        assert samples == []
        collecting.set()
        for _ in range(100):
            await asyncio.sleep(0.001)
            if samples:
                break
        assert samples and all(sample >= 0 for sample in samples)
        collecting.clear()
        count = len(samples)
        await asyncio.sleep(0.01)
        assert len(samples) == count
        sampler.cancel()
        with suppress(asyncio.CancelledError):
            await sampler

    asyncio.run(measure())
