"""Phase 5: real service/worker/cache recovery; model mocks are not inference proof."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from idp.evidence import serde
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import iter_retrievable_blocks
from idp.runtime.cache import StageCache
from idp.runtime.job_contracts import JobRequest
from idp.runtime.lanes import configuration
from idp.runtime.run_job import execute
from idp.runtime.worker import RuntimeWorker

FIX = Path(__file__).parent / "fixtures/generated"
OCR = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="requires real Tesseract"
)


def test_cache_atomic_corrupt_and_concurrent(tmp_path):
    cache = StageCache(tmp_path)
    identity = cache.identity(
        "unit", source_sha256="1" * 64, page=1, config="one", model="pinned"
    )
    validate = lambda p: (
        p if p.get("ok") is True else (_ for _ in ()).throw(ValueError("invalid"))
    )
    assert cache.get(identity, validate) is None
    with ThreadPoolExecutor(4) as pool:
        values = list(
            pool.map(
                lambda i: cache.put(identity, {"ok": True, "winner": i}, validate),
                range(8),
            )
        )
    assert len({v["winner"] for v in values}) == 1
    path = cache._path(identity)
    path.write_text("{partial")
    assert cache.get(identity, validate) is None
    cache.put(identity, {"ok": True}, validate)
    assert cache.get(identity, validate) == {"ok": True}
    assert cache.stats["invalid"] >= 1
    assert cache.get({**identity, "model": "changed"}, validate) is None


@pytest.mark.parametrize(
    "field",
    ["source_sha256", "config", "model", "stage_version", "evidence_contract", "page"],
)
def test_cache_identity_boundaries(tmp_path, field):
    cache = StageCache(tmp_path)
    identity = cache.identity(
        "unit", source_sha256="1" * 64, page=1, config="one", model="rev1"
    )
    cache.put(identity, {"ok": True}, lambda x: x)
    changed = {**identity, field: "different"}
    assert cache.get(changed, lambda x: x) is None


def test_persistent_failed_budget(tmp_path):
    StageCache(tmp_path, job_id="one", max_backend_calls=1).charge_backend()
    from idp.pdf.resource import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        StageCache(tmp_path, job_id="one", max_backend_calls=1).charge_backend()


def test_request_compatibility_and_profiles(tmp_path):
    minimal = {"schema_version": 1, "pdf_path": str(FIX / "native.pdf")}
    old = JobRequest.from_dict(minimal, [FIX])
    new = JobRequest.from_dict(
        {
            "schema_version": 1,
            "input_path": str(FIX / "native.pdf"),
            "execution_profile": "FAST_PREVIEW",
            "requested_canonical_version": 2,
        },
        [FIX],
    )
    assert old.pages == "1" and new.pdf_path == old.pdf_path
    # One resolution rule for every entry point (F8): v1 requests follow the
    # library default, v2 requests need the only engine that can produce v2.
    assert configuration().engine == DeepDocConfig().engine == "unified"
    assert configuration(canonical_version=2).engine == "unified"
    assert DeepDocConfig().canonical_version == 1
    with pytest.raises(ValueError, match="only the unified PDF engine"):
        configuration(canonical_version=2, engine="legacy")
    for profile in ("FAST_PREVIEW", "QUALITY", "HYBRID"):
        assert configuration(profile).canonical_version == 1
    with pytest.raises(ValueError):
        JobRequest.from_dict({**minimal, "schema_version": 2}, [FIX])
    with pytest.raises(ValueError):
        JobRequest.from_dict(minimal, [tmp_path])


def test_worker_native_real_child(tmp_path):
    worker = RuntimeWorker(
        tmp_path / "queue",
        tmp_path / "work",
        [FIX],
        "unused",
        job_timeout=60,
    )
    worker.enqueue(
        {
            "schema_version": 1,
            "pdf_path": str(FIX / "native.pdf"),
            "job_id": "native",
            "requested_canonical_version": 2,
            "language": "eng",
        }
    )
    assert worker.run_once() == "succeeded"
    output = tmp_path / "work/jobs/native/out"
    from idp.publish import load_canonical

    # A v2 canonical read from disk is opened with its referenced L1.
    doc = load_canonical(output / "canonical.json")
    assert doc["schema_version"] == "idp-canonical-2"
    assert json.loads((output / "run_report.json").read_text())["ocr_invocations"] == 0
    assert (output / "commit.json").exists()
    from retrieval.canonical_harness import LocalRagIndex, resolve_citation

    index = LocalRagIndex(tmp_path / "rag.sqlite3")
    index.index(doc)
    hits = index.retrieve(
        "Independent expected", actor="owner", access_check=lambda *args: True
    )
    assert hits and resolve_citation(hits[0], doc)
    assert (
        index.retrieve("Independent", actor="denied", access_check=lambda *args: False)
        == []
    )
@pytest.mark.parametrize("name,expected", [("scan.pdf", [1]), ("mixed.pdf", [2])])
def test_injected_ocr_resume_skips_and_policy_reprojects(tmp_path, name, expected, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    cfg = DeepDocConfig(engine="unified", canonical_version=2, dpi=144)
    root = tmp_path / "cache"
    cache = StageCache(root)
    first = DeepDocService(cfg, stage_cache=cache).process_pdf(
        FIX / name, tmp_path / "one"
    )
    assert cache.stats["backend_calls"] == len(expected)
    cache2 = StageCache(root)
    second = DeepDocService(cfg, stage_cache=cache2).process_pdf(
        FIX / name, tmp_path / "two"
    )
    assert cache2.stats["backend_calls"] == 0 and cache2.stats["hit"] >= len(expected)
    assert first == second
    # Canonical contract changes do not change acquisition identity.
    cache3 = StageCache(root)
    DeepDocService(replace(cfg, canonical_version=1), stage_cache=cache3).process_pdf(
        FIX / name, tmp_path / "v1"
    )
    assert cache3.stats["backend_calls"] == 0
    cache4 = StageCache(root)
    from idp.pdf.publication import PublicationPolicy

    DeepDocService(
        replace(cfg, publication=PublicationPolicy(min_ocr_confidence=0.95)),
        stage_cache=cache4,
    ).process_pdf(FIX / name, tmp_path / "policy")
    assert cache4.stats["backend_calls"] == 0
    cache5 = StageCache(root)
    DeepDocService(replace(cfg, dpi=170), stage_cache=cache5).process_pdf(
        FIX / name, tmp_path / "changed"
    )
    assert cache5.stats["backend_calls"] == len(expected)


def test_interrupted_after_cached_ocr_then_resume(tmp_path, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    from idp.pdf.native.engine import PdfParsingEngine

    cfg = DeepDocConfig(engine="unified", canonical_version=2)
    cache = StageCache(tmp_path / "cache")
    original = PdfParsingEngine.finalize

    def interrupted(*args, **kwargs):
        raise InterruptedError("controlled crash after OCR")

    monkeypatch.setattr(PdfParsingEngine, "finalize", interrupted)
    with pytest.raises(InterruptedError):
        DeepDocService(cfg, stage_cache=cache).process_pdf(
            FIX / "scan.pdf", tmp_path / "out"
        )
    assert cache.stats["backend_calls"] == 1
    monkeypatch.setattr(PdfParsingEngine, "finalize", original)
    resumed = StageCache(tmp_path / "cache")
    doc = DeepDocService(cfg, stage_cache=resumed).process_pdf(
        FIX / "scan.pdf", tmp_path / "out"
    )
    assert (
        doc["schema_version"] == "idp-canonical-2"
        and resumed.stats["backend_calls"] == 0
    )


@pytest.mark.parametrize(
    "suffix,text",
    [
        (".txt", "Independent native text for document dispatch."),
        (".md", "# Header\n\nIndependent Markdown source for dispatch."),
    ],
)
def test_non_pdf_dispatch(tmp_path, suffix, text):
    source = tmp_path / ("input" + suffix)
    source.write_text(text)
    code = execute(
        {
            "job_id": "nonpdf",
            "pdf_path": str(source),
            "options": {"profile": "FAST_PREVIEW"},
        },
        tmp_path / "out",
        tmp_path / "cache",
    )
    assert code == 0
    assert (
        json.loads((tmp_path / "out/canonical.json").read_text())["schema_version"]
        == "idp-canonical-1"
    )


def test_selected_pages_keep_l1_but_exclude_publication(tmp_path):
    cfg = DeepDocConfig(engine="unified", canonical_version=2, pages=(2,))
    doc = DeepDocService(cfg).process_pdf(FIX / "multipage.pdf", tmp_path)
    assert {b["page"] for b in iter_retrievable_blocks(doc)} == {2}
    assert len(doc["pages"]) == 20


@pytest.mark.parametrize("moment", ["after-ocr", "mid-page", "output"])
def test_actual_kill_and_resume(tmp_path, moment, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    import fitz

    source = tmp_path / "two-scans.pdf"
    with fitz.open(FIX / "scan.pdf") as one, fitz.open() as document:
        document.insert_pdf(one)
        document.insert_pdf(one)
        document.save(source)
    marker = tmp_path / "ready"
    command = [
        sys.executable,
        str(Path(__file__).with_name("phase5_crash_child.py")),
        "--input",
        str(source),
        "--out",
        str(tmp_path / "out"),
        "--cache",
        str(tmp_path / "cache"),
        "--marker",
        str(marker),
        "--moment",
        moment,
    ]
    log = tmp_path / "child.log"
    with log.open("w") as handle:
        paths = [str(Path(__file__).resolve().parents[1]), os.environ.get("PYTHONPATH", "")]
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                   env={**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, paths))})
        try:
            deadline = time.monotonic() + 60
            while (
                not marker.exists()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            assert marker.exists(), log.read_text()
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    cfg = DeepDocConfig(engine="unified", canonical_version=2, dpi=144)
    cache = StageCache(tmp_path / "cache")
    started = time.perf_counter()
    resumed = DeepDocService(cfg, stage_cache=cache).process_pdf(
        source, tmp_path / "out"
    )
    resume_seconds = time.perf_counter() - started
    assert cache.stats["backend_calls"] == (1 if moment == "mid-page" else 0)
    clean = DeepDocService(cfg, stage_cache=StageCache(tmp_path / "cache")).process_pdf(
        source, tmp_path / "clean"
    )
    assert resumed == clean
    (tmp_path / "recovery_measurement.json").write_text(
        json.dumps(
            {
                "moment": moment,
                "resume_seconds": resume_seconds,
                "cache_stats": cache.stats,
                "canonical_equal": resumed == clean,
            }
        )
    )


def test_heavy_lease_and_resource_recommendation(tmp_path):
    from idp.runtime.resources import HeavyModelLease, recommended_concurrency

    assert recommended_concurrency(1000, 400, 8) == 1
    assert recommended_concurrency(100, 400, 8) == 0
    with HeavyModelLease(tmp_path / "heavy.lock", time.monotonic() + 1):  # noqa: SIM117 - outer lease must succeed before asserting contention.
        with (
            pytest.raises(TimeoutError),
            HeavyModelLease(tmp_path / "heavy.lock", time.monotonic() + 0.1),
        ):
            pass
    with HeavyModelLease(tmp_path / "heavy.lock", time.monotonic() + 1):
        pass


def test_invalid_pdf_worker_non_retryable(tmp_path):
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"invalid PDF")
    worker = RuntimeWorker(
        tmp_path / "q",
        tmp_path / "w",
        [tmp_path],
        "unused",
        max_attempts=3,
        job_timeout=30,
    )
    worker.enqueue({"job_id": "broken", "pdf_path": str(source), "pages": [1]})
    assert worker.run_once() == "failed"
    state = json.loads((tmp_path / "w/jobs/broken/status.json").read_text())
    assert state["attempt"] == 1
    assert not list((tmp_path / "q/incoming").glob("*.json"))


def test_docx_dispatch_and_source_immutability(tmp_path):
    pytest.importorskip(
        "pypandoc", reason="DOCX optional binding; verified in dedicated interpreter"
    )
    from docx import Document

    source = tmp_path / "input.docx"
    doc = Document()
    doc.add_paragraph("Independent document source for compatible DOCX dispatch.")
    doc.save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        execute(
            {
                "job_id": "docx",
                "pdf_path": str(source),
                "options": {"profile": "HYBRID", "canonical_version": 2},
            },
            tmp_path / "out",
            tmp_path / "cache",
        )
        == 0
    )
    assert (
        json.loads((tmp_path / "out/canonical.json").read_text())["schema_version"]
        == "idp-canonical-1"
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@OCR
def test_image_non_pdf_dispatch(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    font = next(
        p
        for p in (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        )
        if p.is_file()
    )
    image = Image.new("RGB", (1200, 200), "white")
    ImageDraw.Draw(image).text(
        (30, 60),
        "Independent source image for OCR.",
        font=ImageFont.truetype(str(font), 36),
        fill="black",
    )
    source = tmp_path / "image.png"
    image.save(source)
    assert (
        execute(
            {
                "job_id": "image",
                "pdf_path": str(source),
                "options": {"profile": "FAST_PREVIEW", "language": "eng"},
            },
            tmp_path / "out",
            tmp_path / "cache",
        )
        == 0
    )


def test_repeated_native_closes_handles(tmp_path):
    import psutil

    process = psutil.Process()
    if not hasattr(process, "num_fds"):
        pytest.skip("file descriptor counter unavailable")
    counts = []
    for i in range(8):
        DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
            FIX / "native.pdf", tmp_path / str(i)
        )
        counts.append(process.num_fds())
    assert max(counts[2:]) - min(counts[2:]) <= 1


def test_stage_event_aggregation_no_document_content(tmp_path):
    from idp.runtime.events import Events, aggregate

    path = tmp_path / "events.jsonl"
    events = Events(path, "job", "1" * 64)
    events(stage="ocr", cache="hit")
    events(stage="job", duration=2, status="SUCCESS", rss_bytes=100)
    events(
        stage="job",
        duration=5,
        status="FAILED",
        error_code="IO_FAILURE",
        retryable=True,
    )
    report = aggregate([path])
    assert report["p50_seconds"] == 2 and report["p95_seconds"] == 5
    assert report["cache_hit_rate"] == 1 and report["error_counts"]["IO_FAILURE"] == 1
    with pytest.raises(ValueError):
        events(stage="ocr", text="must not be logged")


@pytest.mark.parametrize(
    "reason",
    ["RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "CANCELLED", "REQUEST_DEADLINE"],
)
def test_supervisor_stops_real_process(tmp_path, reason):
    import threading

    class ControlledWorker(RuntimeWorker):
        def _command(self, job, out):
            if reason == "REQUEST_DEADLINE":
                super()._command(job, out)
            code = "import time; data=bytearray(64*1024*1024); time.sleep(30)"
            return [sys.executable, "-c", code]

    worker = ControlledWorker(
        tmp_path / "q",
        tmp_path / "w",
        [FIX],
        "unused",
        job_timeout=1 if reason == "DEADLINE_EXCEEDED" else 30,
        max_worker_rss_mb=16 if reason == "RESOURCE_EXHAUSTED" else 512,
        max_attempts=3,
    )
    worker.enqueue(
        {
            "job_id": "controlled",
            "pdf_path": str(FIX / "native.pdf"),
            "resource_limits": {"timeout_seconds": 0.5}
            if reason == "REQUEST_DEADLINE"
            else {},
        }
    )
    timer = None
    if reason == "CANCELLED":
        timer = threading.Timer(0.3, worker.stop.set)
        timer.start()
    started = time.monotonic()
    try:
        assert worker.run_once() == "failed"
    finally:
        if timer:
            timer.cancel()
            timer.join()
    assert time.monotonic() - started < 10, (
        "supervisor waited for the 30s child instead of stopping it"
    )
    report = json.loads(
        (tmp_path / "w/jobs/controlled/out/runtime_result.json").read_text()
    )
    assert report["error_code"] == (
        "DEADLINE_EXCEEDED" if reason == "REQUEST_DEADLINE" else reason
    )
    assert worker.current_proc is None


def test_transient_retry_backoff_and_real_recovery(tmp_path):
    worker = RuntimeWorker(
        tmp_path / "q",
        tmp_path / "w",
        [FIX],
        "unused",
        job_timeout=60,
    )
    real = worker._execute_batch
    calls = []

    def first_failure(job, out, log):
        calls.append(1)
        if len(calls) > 1:
            return real(job, out, log)
        worker._command(job, out)
        request = json.loads(
            (worker._job_dir(job.job_id) / "service-request.json").read_text()
        )
        out.mkdir(parents=True, exist_ok=True)
        (out / "runtime_result.json").write_text(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_code": "IO_FAILURE",
                    "retryable": True,
                    "attempt_token": request["attempt_token"],
                }
            )
        )
        return 75

    worker._execute = first_failure
    worker.enqueue({"job_id": "retry", "pdf_path": str(FIX / "native.pdf")})
    assert worker.run_once() == "retry"
    assert worker.run_once() is None
    worker._update_status("retry", next_retry_at=0)
    assert worker.run_once() == "succeeded"
    assert worker._status("retry")["attempt"] == 2
    assert (
        len((tmp_path / "w/jobs/retry/worker-events.jsonl").read_text().splitlines())
        == 2
    )


def test_two_workers_same_queue_no_duplicate_commit(tmp_path):
    workers = [
        RuntimeWorker(
            tmp_path / "q",
            tmp_path / "w",
            [FIX],
            "unused",
            worker_id="worker-" + str(i),
            job_timeout=60,
        )
        for i in range(2)
    ]
    for i in range(4):
        workers[0].enqueue(
            {"job_id": "parallel-" + str(i), "pdf_path": str(FIX / "native.pdf")}
        )
    with ThreadPoolExecutor(2) as pool:
        for _ in range(2):
            assert list(pool.map(lambda worker: worker.run_once(), workers)) == [
                "succeeded",
                "succeeded",
            ]
    assert len(list((tmp_path / "q/done").glob("*.json"))) == 4
    assert not list((tmp_path / "q/running").glob("*.json"))
    for i in range(4):
        assert workers[0]._status("parallel-" + str(i))["attempt"] == 1


def test_serde_allowlist_immutable_and_roundtrip(tmp_path):
    from idp.pdf.native.engine import PdfParsingEngine

    record = PdfParsingEngine().extract_source((FIX / "native.pdf").read_bytes())
    assert serde.load(serde.dump(record)) == record
    with pytest.raises(TypeError):
        serde.registry()["untrusted"] = dict


def test_other_worker_cannot_claim_before_retry_classification(tmp_path):
    import threading

    ready, release = threading.Event(), threading.Event()

    class PausedFinalization(RuntimeWorker):
        def _finish_attempt(self, outcome):
            if outcome == "retry":
                ready.set()
                assert release.wait(20)
            return super()._finish_attempt(outcome)

    source = tmp_path / "broken.pdf"
    source.write_bytes(b"invalid PDF")
    args = (tmp_path / "q", tmp_path / "w", [tmp_path, FIX], "unused")
    first = PausedFinalization(
        *args, worker_id="first", job_timeout=30
    )
    second = RuntimeWorker(*args, worker_id="second", job_timeout=30)
    first.enqueue({"job_id": "a-broken", "pdf_path": str(source), "pages": [1]})
    first.enqueue({"job_id": "b-valid", "pdf_path": str(FIX / "native.pdf")})
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first.run_once)
        try:
            assert ready.wait(20)
            b = pool.submit(second.run_once)
            time.sleep(0.2)
            assert not b.done()
        finally:
            release.set()
        assert a.result(timeout=20) == "failed"
        assert b.result(timeout=20) == "succeeded"
    assert first._status("a-broken")["attempt"] == 1
    assert second._status("b-valid")["attempt"] == 1


def test_stale_queue_recovery_runs_real_service(tmp_path):
    worker = RuntimeWorker(
        tmp_path / "q",
        tmp_path / "w",
        [FIX],
        "unused",
        job_timeout=60,
        stale_seconds=1,
    )
    worker.enqueue({"job_id": "stale", "pdf_path": str(FIX / "native.pdf")})
    assert worker.claim_next() is not None
    # A persisted lease from a terminated process, not a live heartbeat.
    path = worker._status_path("stale")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "state": "running",
                "attempt": 1,
                "updated_at": "2000-01-01T00:00:00+00:00",
            }
        )
    )
    assert worker.recover_stale() == ["stale"]
    assert worker.run_once() == "succeeded"
    assert worker._status("stale")["attempt"] == 2


def test_source_swap_between_hash_and_parse_cannot_commit(tmp_path, monkeypatch):
    source = tmp_path / "input.pdf"
    source.write_bytes((FIX / "native.pdf").read_bytes())
    original = DeepDocService.process_pdf

    def changed(self, path, out):
        source.write_bytes((FIX / "columns.pdf").read_bytes())
        return original(self, path, out)

    monkeypatch.setattr(DeepDocService, "process_pdf", changed)
    assert (
        execute(
            {"job_id": "changed", "pdf_path": str(source)},
            tmp_path / "out",
            tmp_path / "cache",
            registry_path=tmp_path / "registry.sqlite3",
        )
        == 65
    )
    assert not (tmp_path / "out/commit.json").exists()
    assert not (tmp_path / "registry.sqlite3").exists()


def test_child_cancels_after_parent_process_dies(tmp_path):
    import os

    import psutil

    parent = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(60)"]
    )
    ready = tmp_path / "ready"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"job_id": "orphan", "pdf_path": str(FIX / "native.pdf")})
    )
    script = (
        "import sys,time\nfrom pathlib import Path\n"
        "from idp.pdf.service import DeepDocService\n"
        "from idp.runtime.run_job import main\n"
        "def wait(*args,**kwargs):\n"
        f"    Path({str(ready)!r}).write_text('ready')\n"
        "    time.sleep(60)\n"
        "DeepDocService.process_pdf=wait\n"
        "raise SystemExit(main())\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            "--request",
            str(request),
            "--out",
            str(tmp_path / "out"),
            "--cache",
            str(tmp_path / "cache"),
        ],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "DEEPDOC_PARENT_PID": str(parent.pid),
            "DEEPDOC_PARENT_CREATED": str(psutil.Process(parent.pid).create_time()),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while (
            not ready.exists() and child.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        assert ready.exists()
        parent.kill()
        parent.wait(timeout=10)
        assert child.wait(timeout=10) == 130
        assert (
            json.loads((tmp_path / "out/runtime_result.json").read_text())["error_code"]
            == "CANCELLED"
        )
    finally:
        for process in (parent, child):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
