"""Tests for the unified Adaptive Hybrid IDP pipeline."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image

from idp.config import NATIVE_TRUSTED_PARSERS, RouterConfig
from idp.ingest import ingest_file
from idp.input.filetypes import InputError, InputLimits
from idp.input.profiler import profile_pdf_document
from idp.ocr.vl_primary import PaddleVLPrimaryReader
from idp.pipeline import orchestrator as orch_mod
from idp.pipeline.page_router import PageRoute, PageRouter
from idp.pipeline.region_router import RegionAction, RegionRouter
from idp.pipeline.scheduler import GpuWorkQueue, ModelPool
from idp.processing.render import PageRenderCache
from idp.validation.quality_gate import check_ingestion_artifacts
from retrieval.canonical_harness import LocalRagIndex

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "generated"


def _make_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def _make_mixed_with_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "Chapter 1. Native Introduction\nThis is clean native text on page one for adaptive parsing.", fontsize=12)
    doc.new_page(width=595, height=842)  # blank page 2
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 100), "Chapter 2. Native Summary\nThis is clean native text on page three after skipping blank page two.", fontsize=12)
    doc.save(path)
    doc.close()


def _make_routing_test_pdf(path: Path) -> None:
    doc = fitz.open()
    # p1: blank
    doc.new_page(width=595, height=842)
    # p2: clean native
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 100), "Clean readable textbook paragraph explaining sets and numbers without broken fonts or tables.", fontsize=12)
    # p3: partial garbled native -> NATIVE_ADAPTIVE (1 of 4 blocks garbled -> 0.25 < 0.35)
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 100), "Readable textbook introduction paragraph one with clean native text.", fontsize=12)
    p3.insert_text((72, 150), "Readable textbook explanation paragraph two explaining real numbers.", fontsize=12)
    p3.insert_text((72, 200), "Readable textbook summary paragraph three with exercises and examples.", fontsize=12)
    p3.insert_text((72, 260), "Broken font fragment (cid:42) here.", fontsize=12)
    # p4: image-only scan -> SCAN_FAST_OCR / SCAN_LAYOUT_HYBRID
    p4 = doc.new_page(width=595, height=842)
    img_path = path.parent / "_scan_tile.png"
    Image.new("RGB", (200, 100), "white").save(img_path)
    p4.insert_image(fitz.Rect(50, 50, 500, 700), filename=str(img_path))
    # p5: repeated URL watermark -> SCAN_*
    p5 = doc.new_page(width=595, height=842)
    p5.insert_text((72, 100), "https://watermark.example.com\nhttps://watermark.example.com\nhttps://watermark.example.com", fontsize=12)
    # p6: scan noise -> SCAN_*
    p6 = doc.new_page(width=595, height=842)
    p6.insert_text((72, 100), "!@#$%", fontsize=12)
    # p7: table grid drawing + native text -> NATIVE_ADAPTIVE
    p7 = doc.new_page(width=595, height=842)
    p7.insert_text((72, 60), "Native paragraph describing the table below with enough words to remain clean native text.", fontsize=12)
    for y in (100, 140, 180, 220):
        p7.draw_line((72, y), (400, y))
    for x in (72, 180, 290, 400):
        p7.draw_line((x, 100), (x, 220))
    doc.save(path)
    doc.close()


def test_page_profiler_and_router_routes_correctly(tmp_path):
    pdf_path = tmp_path / "routing.pdf"
    _make_routing_test_pdf(pdf_path)
    profiles = profile_pdf_document(pdf_path)
    assert len(profiles) == 7

    router = PageRouter()
    d_blank = router.route_page(profiles[0], has_layout=True, has_vlm=True)
    d_clean = router.route_page(profiles[1], has_layout=True, has_vlm=True)
    d_adapt = router.route_page(profiles[2], has_layout=True, has_vlm=True)
    d_scan_fast = router.route_page(profiles[3], has_layout=False, has_vlm=True)
    d_scan_layout = router.route_page(profiles[3], has_layout=True, has_vlm=True)
    d_url = router.route_page(profiles[4], has_layout=False, has_vlm=False)
    d_noise = router.route_page(profiles[5], has_layout=False, has_vlm=False)
    d_grid = router.route_page(profiles[6], has_layout=True, has_vlm=True)

    assert d_blank.route == PageRoute.SKIP_BLANK
    assert d_clean.route == PageRoute.NATIVE_PURE
    assert d_clean.render_required is False
    assert d_adapt.route == PageRoute.NATIVE_ADAPTIVE
    assert "bad_native_blocks" in d_adapt.reasons
    assert d_scan_fast.route == PageRoute.SCAN_FAST_OCR
    assert d_scan_layout.route == PageRoute.SCAN_LAYOUT_HYBRID
    assert d_url.route == PageRoute.SCAN_FAST_OCR
    assert "repeated_url_only_text_layer" in d_url.reasons
    assert d_noise.route == PageRoute.SCAN_FAST_OCR
    assert "scan_noise" in d_noise.reasons
    assert d_grid.route == PageRoute.NATIVE_ADAPTIVE
    assert "table_grid_present" in d_grid.reasons


def test_region_router_sgk_math_selective_early_exit_and_budget():
    router = RegionRouter(RouterConfig(max_vlm_regions_per_page=2))

    # 1) Native SGK page: prose kept (L0), picture preserved, unresolved equation -> VLM
    native_page = {
        "page_id": 1,
        "page_size": [600, 800],
        "blocks": [
            {"block_id": "b1", "block_type": "Text", "bbox": [50, 50, 550, 120], "text": "Bài 1. Giải phương trình bậc hai"},
            {"block_id": "b2", "block_type": "Picture", "bbox": [50, 140, 250, 300], "text": ""},
            {
                "block_id": "b3", "block_type": "Equation", "bbox": [50, 320, 400, 380], "text": "x^2 + 1 = 0",
                "review_flags": [{"code": "FORMULA_TEXT_LAYER_UNVERIFIED", "severity": "warning"}],
            },
            {
                "block_id": "b4", "block_type": "Table", "bbox": [50, 400, 500, 550], "text": "Bảng số liệu",
                "review_flags": [{"code": "TABLE_STRUCTURE_REVIEW", "severity": "warning"}],
            },
        ],
    }
    nat_tasks = router.route_native_page_regions(native_page, has_vlm=True)
    by_bid = {t.source_block_ids[0]: t for t in nat_tasks}
    assert by_bid["b1"].action == RegionAction.NATIVE_KEEP
    assert by_bid["b2"].action == RegionAction.FIGURE_PRESERVE
    assert by_bid["b3"].action == RegionAction.VLM_FORMULA
    assert by_bid["b4"].action == RegionAction.RULED_TABLE_OCR
    assert by_bid["b4"].fallback == RegionAction.VLM_TABLE

    # Without VLM, Equation stays NATIVE_KEEP on CPU
    no_vlm = router.route_native_page_regions(native_page, has_vlm=False)
    assert next(t for t in no_vlm if t.source_block_ids == ["b3"]).action == RegionAction.NATIVE_KEEP

    # 2) OCR page: high-conf prose skips VLM early, math/low-conf escalates, budget keeps Tables/Formulas first
    ocr_page = {
        "page_id": 1,
        "page_size": [600, 800],
        "blocks": [
            {"block_id": "o_clean", "block_type": "Text", "bbox": [40, 40, 560, 90], "text": "Đoạn văn tiếng Việt rõ ràng", "confidence": 0.92},
            {"block_id": "o_low1", "block_type": "Text", "bbox": [40, 110, 560, 160], "text": "Văn bản mờ khó đọc", "confidence": 0.62},
            {"block_id": "o_low2", "block_type": "Text", "bbox": [40, 180, 560, 230], "text": "Tìm x biết 2x + 3 = 7", "confidence": 0.71},
        ],
    }
    layout = [
        {"kind": "text", "bbox": [35, 35, 565, 95], "layout_score": 0.95},
        {"kind": "text", "bbox": [35, 105, 565, 165], "layout_score": 0.90},
        {"kind": "text", "bbox": [35, 175, 565, 235], "layout_score": 0.88},
        {"kind": "formula", "bbox": [35, 260, 400, 320], "layout_score": 0.91},
        {"kind": "formula", "bbox": [35, 340, 400, 400], "layout_score": 0.89},
    ]
    tasks = router.route_ocr_page_regions(ocr_page, layout, has_vlm=True, image_size=(600, 800))
    clean_task = next(t for t in tasks if "o_clean" in t.source_block_ids)
    assert clean_task.action == RegionAction.NATIVE_KEEP
    formula_tasks = [t for t in tasks if t.kind == "Equation"]
    assert all(t.action == RegionAction.VLM_FORMULA and not t.budget_skipped for t in formula_tasks)
    skipped_text = [t for t in tasks if t.budget_skipped]
    assert len(skipped_text) == 2

    # vlm_mode="off" never emits VLM actions; vlm_mode="full" escalates text regions too
    off_tasks = RegionRouter(RouterConfig(vlm_mode="off")).route_ocr_page_regions(
        ocr_page, layout, has_vlm=True, image_size=(600, 800)
    )
    assert all(t.action not in {RegionAction.VLM_FORMULA, RegionAction.VLM_TEXT, RegionAction.VLM_TABLE} for t in off_tasks)
    full_tasks = RegionRouter(RouterConfig(vlm_mode="full", max_vlm_regions_per_page=10)).route_ocr_page_regions(
        ocr_page, layout, has_vlm=True, image_size=(600, 800)
    )
    assert next(t for t in full_tasks if "o_clean" in t.source_block_ids).action == RegionAction.VLM_TEXT


def test_render_cache_lazy_once_rerender_and_evict(tmp_path):
    cache = PageRenderCache(FIXTURES / "native.pdf", tmp_path)
    try:
        assert cache.render_count == 0
        r1 = cache.get_page_image(1)
        r2 = cache.get_page_image(1)
        assert r1.path == r2.path
        assert cache.render_count == 1
        assert cache.rerender_count == 0

        crop, bounds = cache.crop_region(1, [20, 20, 200, 120], [595, 842])
        assert crop.width > 0 and crop.height > 0 and len(bounds) == 4
        assert cache.render_count == 1
        assert 1 in cache._pil_cache

        r3 = cache.get_page_image(1, dpi=360, force_rerender=True)
        assert r3.dpi == 360
        assert cache.rerender_count == 1

        cache.evict_pages([1])
        assert 1 not in cache._pil_cache
    finally:
        cache.close()


def test_scheduler_bounded_gpu_queue_and_warm_model_pool():
    lock = threading.Lock()
    state = {"in_flight": 0, "peak": 0}

    def work(item: int) -> int:
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        time.sleep(0.02)
        with lock:
            state["in_flight"] -= 1
        return item * 10

    with GpuWorkQueue(concurrency=2) as queue:
        out = queue.map_calls(work, range(6))
    assert out == [0, 10, 20, 30, 40, 50]
    assert 1 <= state["peak"] <= 2
    assert queue.metrics()["calls"] == 6

    pool = ModelPool()
    b1 = pool.get_vision_backend("http://127.0.0.1:8111", revision="r1", parallel=2)
    b2 = pool.get_vision_backend("http://127.0.0.1:8111", revision="r1", parallel=2)
    assert b1 is b2
    assert pool.stats()["vision_loads"] == 1


@pytest.mark.parametrize(
    "filename",
    [
        "native.pdf",
        "columns.pdf",
        "table.pdf",
        "formula.pdf",
        "figure.pdf",
        "vietnamese.pdf",
        "encoding.pdf",
        "rotated_cropbox.pdf",
        "multipage.pdf",
        "plain.txt",
        "plain.md",
    ],
)
def test_ingest_file_native_and_text_fixtures(tmp_path, filename):
    out_dir = tmp_path / filename.replace(".", "_")
    report = ingest_file(FIXTURES / filename, out_dir)
    assert report["ingestion_pass"] is True
    assert report["ingestion_auto_publish_pass"] is True
    assert report["telemetry"]["render_count"] == 0
    assert report["telemetry"]["ocr_calls"] == 0
    assert check_ingestion_artifacts(out_dir)["pass"] is True


def test_ingest_error_contracts_and_blank_page_handling(tmp_path):
    with pytest.raises(InputError) as exc_corrupt:
        ingest_file(FIXTURES / "broken.pdf", tmp_path / "broken")
    assert exc_corrupt.value.code == "CORRUPT_FILE"

    blank_pdf = tmp_path / "blank.pdf"
    _make_blank_pdf(blank_pdf)
    with pytest.raises(InputError) as exc_empty:
        ingest_file(blank_pdf, tmp_path / "blank_out")
    assert exc_empty.value.code == "NEEDS_OCR_ENGINE"

    mixed_blank_pdf = tmp_path / "mixed_blank.pdf"
    _make_mixed_with_blank_pdf(mixed_blank_pdf)
    out = tmp_path / "mixed_blank_out"
    res = ingest_file(mixed_blank_pdf, out)
    assert res["pages"] == 3
    assert res["ingestion_pass"] is True
    assert res["ingestion_auto_publish_pass"] is True
    assert res["page_routes"]["SKIP_BLANK"] == 1
    assert res["telemetry"]["render_count"] == 0
    can = json.loads((out / "canonical.json").read_text(encoding="utf-8"))
    assert can["pages"][1]["status"] == "blank"


def test_scan_and_image_selective_vlm_with_mocked_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(orch_mod, "choose_ocr_language", lambda req: (req or "vie", False))

    def fake_ocr(image_path, work_dir, page_id, *, lang="vie", profile="general", timeout=120):
        return [
            {
                "bbox": [40, 40, 400, 75],
                "text": "Đoạn văn bản sạch rõ ràng không cần model thị giác.",
                "words": [],
                "confidence": 93.0,
            },
            {
                "bbox": [40, 480, 400, 520],
                "text": "x^2 + y^2 = z^2",
                "words": [],
                "confidence": 64.0,
            },
        ]

    monkeypatch.setattr(orch_mod, "ocr_page_image", fake_ocr)
    monkeypatch.setattr(orch_mod, "detect_panels", lambda _p: [])

    vlm_calls: list[str] = []

    class FakeVLReader:
        identity = {"name": "fake_vl", "revision": "v1"}
        cacheable = True
        parallel = 2

        def __call__(self, crop, kind):
            vlm_calls.append(kind)
            return [("x^2", 0.95, []), (" ", 0.99, []), ("+", 0.95, []), (" ", 0.99, []), ("y^2", 0.95, [])]

    scan_out = tmp_path / "scan_out"
    res = ingest_file(FIXTURES / "scan.pdf", scan_out, vl_reader=FakeVLReader())
    assert res["pages"] == 1
    assert res["telemetry"]["render_count"] == 1
    assert res["telemetry"]["vlm_skipped_early_exit"] >= 1
    assert len(vlm_calls) == 1  # Only low-conf/math block escalated; clean prose exited on CPU

    # Image upload happy path + NO_TEXT_IN_IMAGE guard
    img_path = tmp_path / "sample.png"
    Image.new("RGB", (400, 200), "white").save(img_path)
    img_out = tmp_path / "img_out"
    img_res = ingest_file(img_path, img_out)
    assert img_res["pages"] == 1
    assert img_res["blocks"] >= 2

    monkeypatch.setattr(orch_mod, "ocr_page_image", lambda *a, **k: [])
    with pytest.raises(InputError) as exc_img:
        ingest_file(img_path, tmp_path / "empty_img_out")
    assert exc_img.value.code == "NO_TEXT_IN_IMAGE"
    with pytest.raises(InputError) as exc_scan_empty:
        ingest_file(FIXTURES / "scan.pdf", tmp_path / "empty_scan_out")
    assert exc_scan_empty.value.code == "NEEDS_OCR_ENGINE"


def test_registry_cache_rag_roundtrip_and_document_contract(tmp_path):
    # Check services/document import contract cleanly
    assert issubclass(InputError, Exception)
    assert InputLimits().max_pages >= 1
    assert PaddleVLPrimaryReader.__name__ in {"PaddleVLPrimaryReader", "PaddleVisionBackend"}

    reg_db = tmp_path / "registry.sqlite"
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    r1 = ingest_file(FIXTURES / "vietnamese.pdf", out1, registry_path=reg_db, scope="unit")
    assert r1.get("cache_hit") is not True
    r2 = ingest_file(FIXTURES / "vietnamese.pdf", out2, registry_path=reg_db, scope="unit")
    assert r2["cache_hit"] is True
    assert (out2 / "canonical.json").is_file()
    assert (out2 / "ingestion_report.json").is_file()
    assert (out2 / "report.json").is_file()
    assert (out2 / "review_queue.jsonl").is_file()

    canonical = json.loads((out1 / "canonical.json").read_text(encoding="utf-8"))
    assert canonical["schema_version"] == "idp-canonical-1"

    rag_index = LocalRagIndex(tmp_path / "rag.sqlite")
    indexed = rag_index.index(canonical, trusted_parsers=NATIVE_TRUSTED_PARSERS)
    assert indexed >= 1
    hits = rag_index.retrieve("phương trình", actor="student-1", access_check=lambda *_: True, top_k=3)
    assert len(hits) >= 1


def _dispatch_to_handler(handler_cls, req) -> bytes:
    """Invoke a BaseHTTPRequestHandler in-memory without opening OS TCP sockets."""
    import io

    method = req.get_method()
    selector = req.selector
    body = req.data or b""
    hdr_lines = [f"{method} {selector} HTTP/1.1"]
    headers = {**dict(req.unredirected_hdrs), **dict(req.headers)}
    if body and "Content-length" not in headers and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    for k, v in headers.items():
        hdr_lines.append(f"{k}: {v}")
    raw_req = ("\r\n".join(hdr_lines) + "\r\n\r\n").encode("latin-1") + body

    in_buf = io.BytesIO(raw_req)
    out_buf = io.BytesIO()

    class _FakeSock:
        def makefile(self, mode, *args, **kwargs):
            return in_buf if "r" in mode else out_buf

        def sendall(self, data):
            out_buf.write(data)

    handler_cls(_FakeSock(), ("127.0.0.1", 55555), None)
    raw_resp = out_buf.getvalue()
    head, _, resp_body = raw_resp.partition(b"\r\n\r\n")
    status_code = int(head.splitlines()[0].split()[1])
    if status_code >= 400:
        raise RuntimeError(f"HTTP {status_code}: {resp_body.decode('utf-8', 'replace')}")
    return resp_body


class _InMemoryResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, limit: int | None = None) -> bytes:
        return self._payload if limit is None else self._payload[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_remote_layout_server_client_and_fallback(tmp_path, monkeypatch):
    import urllib.request

    from idp.backends.layout import RemoteLayoutDetector
    from idp.backends.vision_ocr import LocalRegionError
    from tools.gpu_layout_server import create_server

    with pytest.raises(LocalRegionError, match="loopback"):
        RemoteLayoutDetector("https://gpu.example.com:8112")

    calls = {"predict": 0}

    class FakeLayoutBackend:
        identity = {"name": "PP-DocLayoutV3", "device": "gpu:0", "layout_policy": "v3_vl16"}
        revision = "rev-layout-1"

        def predict_image_bytes(self, raw_bytes: bytes) -> list[dict]:
            calls["predict"] += 1
            return [
                {"bbox": [10, 20, 120, 60], "kind": "text", "layout_score": 0.94},
                {"bbox": [10, 70, 120, 110], "kind": "formula", "layout_score": 0.89},
            ]

    server = create_server("127.0.0.1", 0, FakeLayoutBackend())
    handler_cls = server.RequestHandlerClass
    server.server_close()

    class _MemOpener:
        def open(self, req, timeout=None):
            if ":9/" in req.full_url:
                raise OSError("connection refused")
            return _InMemoryResponse(_dispatch_to_handler(handler_cls, req))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _MemOpener())

    client = RemoteLayoutDetector(
        "http://127.0.0.1:8112",
        layout_policy="v3_vl16",
        revision="rev-layout-1",
        max_pixels=65_536,  # Force 2x downscale on 512x512 image -> rescale 2x back!
    )
    health = client.health()
    assert health["status"] == "ok"
    assert health["revision"] == "rev-layout-1"

    big_img = tmp_path / "big.png"
    Image.new("RGB", (512, 512), "white").save(big_img)
    boxes1 = client(big_img)
    boxes2 = client(big_img)  # Cached by SHA-256
    assert calls["predict"] == 1
    assert boxes1 == boxes2
    assert len(boxes1) == 2
    assert boxes1[0]["bbox"] == pytest.approx([20.0, 40.0, 240.0, 120.0], rel=0.02)

    # Transient layout server failure falls back to CPU OCR + NEEDS_REVIEW (not hard FAILED)
    monkeypatch.setattr(orch_mod, "choose_ocr_language", lambda req: (req or "vie", False))
    monkeypatch.setattr(
        orch_mod,
        "ocr_page_image",
        lambda *a, **k: [{"bbox": [40, 40, 400, 80], "text": "Văn bản dự phòng khi mất kết nối layout.", "words": [], "confidence": 91.0}],
    )
    monkeypatch.setattr(orch_mod, "detect_panels", lambda _p: [])

    broken_client = RemoteLayoutDetector("http://127.0.0.1:9", revision="down", timeout=0.2)
    fallback_out = tmp_path / "layout_down_out"
    report = ingest_file(FIXTURES / "scan.pdf", fallback_out, layout_detector=broken_client)
    assert report["ingestion_review_assisted_pass"] is True
    assert report["ingestion_auto_publish_pass"] is False


def test_verify_remote_stack_end_to_end_with_loopback_servers(monkeypatch):
    import urllib.request
    from http.server import BaseHTTPRequestHandler

    from idp.verify_remote import verify_remote_stack
    from tools.gpu_layout_server import create_server

    monkeypatch.setattr(orch_mod, "choose_ocr_language", lambda req: (req or "vie", False))
    monkeypatch.setattr(
        orch_mod,
        "ocr_page_image",
        lambda *a, **k: [{"bbox": [60, 170, 650, 260], "text": "x^2 - 5x + 6 = 0", "words": [], "confidence": 65.0}],
    )
    monkeypatch.setattr(orch_mod, "detect_panels", lambda _p: [])

    state = {"with_logprobs": True}

    class FakeLlamaHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):  # noqa: N802
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            _ = self.rfile.read(length)
            logprobs = (
                {
                    "content": [
                        {"token": "x^2", "logprob": -0.02, "top_logprobs": []},
                        {"token": " - 5x + 6 = 0", "logprob": -0.03, "top_logprobs": []},
                    ]
                }
                if state["with_logprobs"]
                else None
            )
            resp = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "x^2 - 5x + 6 = 0"},
                        "logprobs": logprobs,
                    }
                ]
            }
            body = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class FakeLayoutBackend:
        identity = {"name": "PP-DocLayoutV3", "device": "gpu:0", "layout_policy": "v3_vl16"}
        revision = "smoke-layout"

        def predict_image_bytes(self, _raw: bytes) -> list[dict]:
            return [{"bbox": [50, 160, 660, 270], "kind": "formula", "layout_score": 0.96}]

    lay_server = create_server("127.0.0.1", 0, FakeLayoutBackend())
    lay_handler = lay_server.RequestHandlerClass
    lay_server.server_close()

    class _RouterOpener:
        def open(self, req, timeout=None):
            cls = FakeLlamaHandler if ":8111/" in req.full_url else lay_handler
            return _InMemoryResponse(_dispatch_to_handler(cls, req))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _RouterOpener())

    summary = verify_remote_stack(
        vl_url="http://127.0.0.1:8111",
        layout_url="http://127.0.0.1:8112",
    )
    assert summary["pass"] is True
    assert summary["checks"]["vl_logprobs"]["pass"] is True
    assert summary["checks"]["layout_boxes"]["box_count"] == 1
    assert summary["checks"]["end_to_end_gpu_canonical"]["vl_sourced_blocks"] >= 1

    # Missing logprobs must fail loudly instead of silently passing
    state["with_logprobs"] = False
    with pytest.raises(RuntimeError, match="logprobs"):
        verify_remote_stack(
            vl_url="http://127.0.0.1:8111",
            layout_url="http://127.0.0.1:8112",
        )


def test_encode_image_data_url_downscales_oversized_crops_and_table_budget(tmp_path, monkeypatch):
    import base64
    import io

    from idp.backends import vision_ocr

    big_img = Image.new("RGB", (2400, 1200), "white")  # 2.88M px > 2.0M
    data_url = vision_ocr._encode_image_data_url(big_img, max_pixels=2_000_000)
    assert data_url.startswith("data:image/jpeg;base64,")
    decoded_bytes = base64.b64decode(data_url.split(",", 1)[1])
    with Image.open(io.BytesIO(decoded_bytes)) as decoded:
        assert decoded.width * decoded.height <= 2_000_000
        assert abs(decoded.width / decoded.height - 2.0) < 0.05

    png_path = tmp_path / "big_table.png"
    big_img.save(png_path, format="PNG")
    path_url = vision_ocr._encode_image_data_url(png_path, max_pixels=2_000_000)
    assert path_url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(path_url.split(",", 1)[1]))) as decoded:
        assert decoded.width * decoded.height <= 2_000_000

    # Hard upper pixel cap still raises LocalRegionError("IMAGE_PIXELS")
    monkeypatch.setattr(vision_ocr, "MAX_HARD_INPUT_PIXELS", 100_000)
    with pytest.raises(vision_ocr.LocalRegionError) as exc_info:
        vision_ocr._encode_image_data_url(Image.new("RGB", (500, 300), "white"), max_pixels=50_000)
    assert exc_info.value.code == "IMAGE_PIXELS"

    # PaddleVisionBackend.read_region_structured boosts Table max_tokens from 1024 -> 2048 by default
    captured_tokens: list[int] = []
    monkeypatch.setattr(
        vision_ocr,
        "read_region",
        lambda _img, _kind, **kw: captured_tokens.append(kw["max_tokens"]) or {"table_html": "<table><tr><td>a</td></tr></table>"},
    )
    backend = vision_ocr.PaddleVisionBackend("http://127.0.0.1:8111", max_tokens=1024)
    backend.read_region_structured(png_path, "Table")
    backend.read_region_structured(png_path, "Text")
    assert captured_tokens == [2048, 1024]


def test_region_router_inline_formula_folding_pagenumber_and_full_merge():
    from idp.backends.layout import normalize_layout_kind

    assert normalize_layout_kind("number") == "PageNumber"

    router = RegionRouter(RouterConfig(vlm_mode="selective", max_vlm_regions_per_page=10))
    ocr_page = {
        "page_id": 1,
        "page_size": [600, 800],
        "blocks": [
            {"block_id": "b_text", "block_type": "Text", "bbox": [40, 100, 520, 130], "text": "Xét câu n chia hết cho 2", "confidence": 0.94},
            {"block_id": "b_num", "block_type": "Text", "bbox": [290, 760, 315, 785], "text": "3", "confidence": 0.95},
        ],
    }
    layout = [
        {"kind": "text", "bbox": [35, 95, 525, 135], "layout_score": 0.95},
        {"kind": "inline_formula", "bbox": [240, 102, 265, 126], "layout_score": 0.85},  # enclosed inside text box
        {"kind": "inline_formula", "bbox": [10, 200, 24, 218], "layout_score": 0.70},  # tiny isolated speck
        {"kind": "display_formula", "bbox": [120, 300, 380, 350], "layout_score": 0.92},  # standalone formula
        {"kind": "number", "bbox": [285, 755, 320, 788], "layout_score": 0.90},
    ]
    tasks = router.route_ocr_page_regions(ocr_page, layout, has_vlm=True, image_size=(600, 800))
    assert not any(t.action == RegionAction.VLM_FORMULA and "lay_001" in t.region_id for t in tasks)
    text_task = next(t for t in tasks if "b_text" in t.source_block_ids)
    assert text_task.action == RegionAction.VLM_TEXT
    assert "inline_formula_detected" in text_task.reasons
    eq_tasks = [t for t in tasks if t.action == RegionAction.VLM_FORMULA]
    assert len(eq_tasks) == 1
    assert [round(x) for x in eq_tasks[0].bbox] == [120, 300, 380, 350]
    num_task = next(t for t in tasks if t.kind == "PageNumber")
    assert num_task.action == RegionAction.SKIP_DECORATIVE
    assert "b_num" in num_task.source_block_ids

    # vlm_mode="full" merges adjacent Text regions above budget without crossing SectionHeader
    dense_router = RegionRouter(RouterConfig(vlm_mode="full", max_vlm_regions_per_page=3))
    dense_layout = [
        {"kind": "doc_title", "bbox": [40, 20, 300, 50], "layout_score": 0.95},
        {"kind": "text", "bbox": [40, 60, 480, 85], "layout_score": 0.9},
        {"kind": "text", "bbox": [40, 95, 480, 120], "layout_score": 0.9},
        {"kind": "text", "bbox": [40, 130, 480, 155], "layout_score": 0.9},
        {"kind": "paragraph_title", "bbox": [40, 200, 320, 230], "layout_score": 0.93},
        {"kind": "text", "bbox": [40, 240, 480, 265], "layout_score": 0.9},
        {"kind": "text", "bbox": [40, 275, 480, 300], "layout_score": 0.9},
    ]
    dense_blocks = [
        {"block_id": f"db{i}", "block_type": "Text", "bbox": item["bbox"], "text": f"Dòng {i}", "confidence": 0.9}
        for i, item in enumerate(dense_layout)
    ]
    full_tasks = dense_router.route_ocr_page_regions(
        {"page_id": 1, "page_size": [600, 800], "blocks": dense_blocks},
        dense_layout,
        has_vlm=True,
        image_size=(600, 800),
    )
    assert sum(1 for t in full_tasks if t.action == RegionAction.VLM_TEXT) <= 4
    assert sum(1 for t in full_tasks if t.budget_skipped) <= 1
    sec_tasks = [t for t in full_tasks if t.kind == "SectionHeader"]
    assert len(sec_tasks) == 2
    assert all(not any(b in {"db0", "db4"} for b in t.source_block_ids) for t in full_tasks if t.kind == "Text")


def test_section_header_table_dedup_full_budget_guard_and_retry_pixels(tmp_path):
    from idp.canonical import build_canonical
    from idp.config import ParseConfig, RenderConfig
    from idp.pipeline.ocr_executor import (
        _apply_layout_block_types,
        _suppress_table_overlapping_ocr_blocks,
        execute_ocr_region_tasks,
        run_scan_page_with_retry,
    )
    from idp.pipeline.page_router import PageDecision, PageRoute
    from idp.pipeline.region_router import RegionTask
    from idp.pipeline.scheduler import AdaptiveScheduler
    from idp.evidence.recovery import RecoveryOptions
    from idp.processing.figure import assign_section_paths
    from idp.validation.quality_gate import audit_canonical, digital_consistency_audit
    from rag.indexing import canonical_to_markdown, locate_spans_in_canonical

    img_path = tmp_path / "page.png"
    Image.new("RGB", (600, 800), "white").save(img_path)

    # 1) SectionHeader survives VLM_TEXT + NATIVE_KEEP and populates locate_spans_in_canonical
    page = {
        "page_id": 1,
        "page_size": [600, 800],
        "processing_status": "ok",
        "review": [],
        "blocks": [
            {"block_id": "h1", "block_type": "Text", "bbox": [40, 30, 400, 60], "text": "Chương 1. Mệnh đề", "source": "tesseract_ocr", "confidence": 0.92, "review_flags": []},
            {"block_id": "h2", "block_type": "Text", "bbox": [40, 120, 400, 150], "text": "1. Mệnh đề toán học", "source": "tesseract_ocr", "confidence": 0.72, "review_flags": []},
            {"block_id": "body", "block_type": "Text", "bbox": [40, 170, 500, 210], "text": "Khẳng định đúng hoặc sai.", "source": "tesseract_ocr", "confidence": 0.95, "review_flags": []},
            {"block_id": "pnum", "block_type": "Text", "bbox": [290, 760, 310, 785], "text": "1", "source": "tesseract_ocr", "confidence": 0.95, "review_flags": []},
            {"block_id": "tcell", "block_type": "Text", "bbox": [80, 320, 220, 345], "text": "ô bị trùng", "source": "tesseract_ocr", "confidence": 0.91, "review_flags": []},
            {
                "block_id": "tbl_ok",
                "block_type": "Table",
                "bbox": [50, 300, 550, 450],
                "text": "Học phần",
                "table_html": "<table><tr><td>Học phần</td></tr></table>",
                "table_cells": [{"row": 0, "column": 0, "rowspan": 1, "colspan": 1, "is_header": False, "text": "Học phần"}],
                "source": "paddleocr_vl_gguf",
                "confidence": None,
                "review_flags": [],
            },
        ],
    }
    tasks = [
        RegionTask(region_id="r0", kind="SectionHeader", bbox=[40, 30, 400, 60], action=RegionAction.NATIVE_KEEP, source_block_ids=["h1"]),
        RegionTask(region_id="r1", kind="SectionHeader", bbox=[40, 120, 400, 150], action=RegionAction.VLM_TEXT, source_block_ids=["h2"], line_boxes=[(40, 120, 400, 150)]),
        RegionTask(region_id="r2", kind="PageNumber", bbox=[290, 760, 310, 785], action=RegionAction.SKIP_DECORATIVE, source_block_ids=["pnum"]),
    ]

    class StubVL:
        identity = {"name": "stub-vl"}

        def __call__(self, image, kind):
            assert kind == "Text"
            return [("1. Mệnh đề toán học", 0.99, [])]

    cache = PageRenderCache(None, tmp_path, precomputed_images={1: img_path})
    try:
        scheduler = AdaptiveScheduler()
        telemetry = {"ocr_calls": 0, "vlm_calls": 0}
        execute_ocr_region_tasks(
            page, tasks, tmp_path, tmp_path / "assets",
            image_path=img_path, lang="vie", render_cache=cache,
            scheduler=scheduler, telemetry=telemetry,
            config=ParseConfig(), vl_reader=StubVL(),
            inc_ocr_calls=lambda d, n: None,
        )
        _suppress_table_overlapping_ocr_blocks(page)
        _apply_layout_block_types(page, tasks)
        assign_section_paths(page["blocks"])
    finally:
        cache.close()

    by_text = {b["text"]: b for b in page["blocks"]}
    assert by_text["Chương 1. Mệnh đề"]["block_type"] == "SectionHeader"
    assert by_text["1. Mệnh đề toán học"]["block_type"] == "SectionHeader"
    assert by_text["1"]["block_type"] == "PageNumber"
    assert "ô bị trùng" not in by_text

    doc = build_canonical([page], "scan.pdf", "d" * 64, "scan", expected_pages=[1])
    md, _ = canonical_to_markdown(doc)
    assert "## Chương 1. Mệnh đề" in md
    assert "## 1. Mệnh đề toán học" in md
    pos = md.index("Khẳng định đúng hoặc sai.")
    loc = locate_spans_in_canonical(doc, [(pos, pos + 10)])
    assert loc is not None and loc.get("section") == "1. Mệnh đề toán học"

    # 2) Unresolved Table keeps structured_region provenance and does not poison source_provenance / table consistency
    unresolved_page = {
        "page_id": 1,
        "page_size": [600, 800],
        "processing_status": "ok",
        "review": [],
        "blocks": [
            {"block_id": "ok1", "block_type": "Text", "bbox": [40, 40, 400, 70], "text": "Đoạn bình thường.", "source": "tesseract_ocr", "confidence": 0.95, "review_flags": []},
        ],
    }
    cache2 = PageRenderCache(None, tmp_path / "u", precomputed_images={1: img_path})
    try:
        from idp.pipeline.ocr_executor import execute_ruled_table_task
        execute_ruled_table_task(
            unresolved_page,
            RegionTask(region_id="tbl0", kind="Table", bbox=[50, 200, 550, 600], action=RegionAction.RULED_TABLE_OCR),
            target_block=None,
            out_dir=tmp_path / "u",
            assets_dir=tmp_path / "u" / "assets",
            lang="vie",
            render_cache=cache2,
            scheduler=AdaptiveScheduler(),
            telemetry={"ocr_calls": 0},
            region_timeout_seconds=1.0,
            vl_reader=None,
            inc_ocr_calls=lambda d, n: None,
            force_vlm=True,
        )
    finally:
        cache2.close()
    udoc = build_canonical([unresolved_page], "u.pdf", "e" * 64, "u", expected_pages=[1])
    uaudit = audit_canonical(udoc)
    ucons = digital_consistency_audit([unresolved_page], {}, "pdf_ocr", [])
    assert uaudit["checks"]["source_provenance"]["pass"] is True
    assert ucons["checks"]["table_metrics_consistent"]["pass"] is True

    # 3) Budget-skipped full mode retains non-VLM blocks instead of dropping them
    partial_page = {
        "page_id": 1,
        "page_size": [600, 800],
        "processing_status": "ok",
        "review": [],
        "blocks": [
            {"block_id": "keep_me", "block_type": "Text", "bbox": [40, 400, 400, 430], "text": "Khối vượt budget phải giữ lại.", "source": "tesseract_ocr", "confidence": 0.92, "review_flags": []},
            {"block_id": "run_me", "block_type": "Text", "bbox": [40, 40, 400, 70], "text": "Khối chạy VLM.", "source": "tesseract_ocr", "confidence": 0.90, "review_flags": []},
        ],
    }
    ptasks = [
        RegionTask(region_id="p0", kind="Text", bbox=[40, 40, 400, 70], action=RegionAction.VLM_TEXT, source_block_ids=["run_me"], line_boxes=[(40, 40, 400, 70)]),
        RegionTask(region_id="p1", kind="Text", bbox=[40, 400, 400, 430], action=RegionAction.NATIVE_KEEP, source_block_ids=["keep_me"], budget_skipped=True),
    ]
    full_cfg = ParseConfig(router=RouterConfig(vlm_mode="full", max_vlm_regions_per_page=1))
    cache3 = PageRenderCache(None, tmp_path / "f", precomputed_images={1: img_path})
    try:
        class FullStub:
            identity = {"name": "stub-vl"}

            def __call__(self, image, kind):
                return [("Khối chạy VLM.", 0.99, [])]

        execute_ocr_region_tasks(
            partial_page, ptasks, tmp_path / "f", tmp_path / "f" / "assets",
            image_path=img_path, lang="vie", render_cache=cache3,
            scheduler=AdaptiveScheduler(),
            telemetry={"ocr_calls": 0},
            config=full_cfg, vl_reader=FullStub(),
            inc_ocr_calls=lambda d, n: None,
        )
    finally:
        cache3.close()
    assert any(b.get("block_id") == "keep_me" for b in partial_page["blocks"])

    # 4) Retry render lifts max_pixels proportionally to retry_dpi (on non-blank image)
    from PIL import ImageDraw

    retry_img_path = tmp_path / "retry_nonblank.png"
    retry_img = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(retry_img)
    for y_pos in range(40, 200, 25):
        draw.line((40, y_pos, 320, y_pos), fill="black", width=3)
    retry_img.save(retry_img_path)

    recorded_renders: list[tuple[int | None, int | None, bool]] = []

    class FakeRenderCache:
        pdf_path = tmp_path / "dummy.pdf"
        precomputed: set[int] = set()

        def get_page_image(self, pid, *, dpi=None, max_pixels=None, force_rerender=False):
            recorded_renders.append((dpi, max_pixels, force_rerender))
            return type("R", (), {"path": retry_img_path, "sha256": "a" * 64, "dpi": dpi or 220, "width": 600, "height": 800})()

        def register_external_image(self, *_a, **_k):
            pass

        def crop_region(self, *_a, **_k):
            return Image.new("RGB", (50, 50), "white"), [0, 0, 50, 50]

    retry_cfg = ParseConfig(render=RenderConfig(base_dpi=220, retry_dpi=360, max_page_pixels=4_000_000))
    run_scan_page_with_retry(
        PageDecision(page_id=1, route=PageRoute.SCAN_FAST_OCR, level=2, reasons=[], render_required=True, layout_required=False, ocr_required=True, vlm_candidate=False, native_usable=False, risk_score=1.0),
        profile_width=600,
        profile_height=800,
        ocr_reason=None,
        out_dir=tmp_path / "retry_out",
        assets_dir=tmp_path / "retry_out" / "assets",
        lang="vie",
        profile_name="general",
        render_cache=FakeRenderCache(),  # type: ignore[arg-type]
        scheduler=AdaptiveScheduler(),
        telemetry={"ocr_calls": 0, "region_actions": {}, "vlm_skipped_early_exit": 0, "vlm_budget_skipped": 0},
        config=retry_cfg,
        detector=None,
        vl_reader=None,
        region_enricher=None,
        dual_reader=None,
        region_router=RegionRouter(retry_cfg.router),
        recovery_options=RecoveryOptions(),
        has_vlm=False,
        record_task_telemetry=lambda *_a: None,
        inc_ocr_calls=lambda *_a: None,
        ocr_page_image_fn=lambda *_a, **_k: [{"bbox": [40, 40, 300, 70], "text": "low", "confidence": 40.0, "words": []}],
        detect_panels_fn=lambda *_a: [],
    )
    assert any(force and dpi == 360 and (max_px or 0) > 4_000_000 for dpi, max_px, force in recorded_renders)


def test_structural_section_header_filtering_merging_and_duplicate_suppression(tmp_path):
    from PIL import Image
    from idp.backends.native.pdf import make_block
    from idp.config import ParseConfig
    from idp.evidence.vl_fusion import fuse_vl_regions
    from idp.pipeline.ocr_executor import _apply_layout_block_types, execute_ruled_table_task
    from idp.pipeline.region_router import RegionAction, RegionTask
    from idp.pipeline.scheduler import AdaptiveScheduler
    from idp.processing.figure import is_structural_section_header, merge_adjacent_section_headers
    from idp.processing.render import PageRenderCache

    for non_header in (
        "Giải",
        "Giài",
        "}ví dụó",
        "Ví dụ 2. Phát biểu mệnh đề phủ định:",
        "》 Luyện tập 6",
        "Em có biết?",
        "z Em có biết? ®",
        "¡ KIẾN THỨC, KĨ NĂNG",
        "THUẬT NGỮ",
        "Chú ý.",
    ):
        assert not is_structural_section_header(non_header), f"should reject {non_header!r}"

    for valid_header in (
        "CHƯƠNG II",
        "1. MỆNH ĐỀ, MỆNH ĐỀ CHỨA BIẾN",
        "a. Mệnh đề",
        "BÀI TẬP",
        "1. Một số thông tin về chương trình đào tạo",
        "Đề 2",
    ):
        assert is_structural_section_header(valid_header), f"should accept {valid_header!r}"

    # Multi-line display banner merges consecutively, but does not absorb numbered heading or next page
    blocks = [
        {**make_block("h1", "SectionHeader", [100, 50, 320, 75], "CHƯƠNG II", "# CHƯƠNG II"), "page": 1},
        {**make_block("h2", "SectionHeader", [100, 82, 340, 108], "BẤT PHƯƠNG TRÌNH VÀ", "## BẤT PHƯƠNG TRÌNH VÀ"), "page": 1},
        {**make_block("h3", "SectionHeader", [100, 114, 340, 140], "BẬC NHẤT HAI ẨN", "## BẬC NHẤT HAI ẨN"), "page": 1},
        {**make_block("h4", "SectionHeader", [100, 148, 340, 174], "1. MỆNH ĐỀ", "## 1. MỆNH ĐỀ"), "page": 1},
        {**make_block("h5", "SectionHeader", [100, 180, 340, 204], "a. Mệnh đề", "### a. Mệnh đề"), "page": 1},
    ]
    merged = merge_adjacent_section_headers(blocks)
    assert len(merged) == 3
    assert merged[0]["text"] == "CHƯƠNG II BẤT PHƯƠNG TRÌNH VÀ BẬC NHẤT HAI ẨN"
    assert merged[1]["text"] == "1. MỆNH ĐỀ"
    assert merged[2]["text"] == "a. Mệnh đề"

    # Non-structural SectionHeader rejected by both _apply_layout_block_types & fuse_vl_regions,
    # and wider same-line OCR duplicate ('z Em có biết? ®') suppressed when VLM box covers it vertically.
    page = {
        "page_id": 6,
        "page_size": [600, 800],
        "blocks": [
            make_block("b_dup", "Text", [80, 700, 260, 725], "z Em có biết? ®", "z Em có biết? ®"),
            make_block("b_nat", "Text", [80, 400, 200, 420], "Giải", "Giải"),
            make_block("b_hdr", "Text", [80, 50, 320, 75], "BÀI TẬP", "BÀI TẬP"),
        ],
    }
    _apply_layout_block_types(
        page,
        [
            RegionTask(region_id="r0", kind="SectionHeader", bbox=[80, 50, 320, 75], action=RegionAction.NATIVE_KEEP, source_block_ids=["b_hdr"]),
            RegionTask(region_id="r1", kind="SectionHeader", bbox=[80, 400, 200, 420], action=RegionAction.NATIVE_KEEP, source_block_ids=["b_nat"]),
        ],
    )
    assert page["blocks"][2]["block_type"] == "SectionHeader"
    assert page["blocks"][1]["block_type"] == "Text"

    summary = fuse_vl_regions(
        page,
        [("SectionHeader", (100.0, 701.0, 220.0, 724.0), [(100.0, 701.0, 220.0, 724.0)])],
        [([("Em có biết?", 0.99, [])], None)],
        replace_all_text=False,
    )
    assert summary["lines"] == 1
    vl_blk = next(b for b in page["blocks"] if str(b.get("block_id", "")).startswith("p0006_vl"))
    assert vl_blk["block_type"] == "Text"  # non-structural label demoted to Text
    assert not any(b.get("block_id") == "b_dup" for b in page["blocks"])

    # execute_ruled_table_task preserves VLM error reason in structured_provenance
    img_path = tmp_path / "p13.png"
    Image.new("RGB", (400, 300), "white").save(img_path)
    tbl_page = {"page_id": 13, "page_size": [400, 300], "blocks": [], "review": []}
    cache = PageRenderCache(None, tmp_path / "rc", precomputed_images={13: img_path})

    class FailingVL:
        timeout = 10.0

        def read_region_structured(self, *_a, **_kw):
            raise RuntimeError("boom table read")

    try:
        execute_ruled_table_task(
            tbl_page,
            RegionTask(
                region_id="lay_000",
                kind="Table",
                bbox=[10, 10, 390, 290],
                action=RegionAction.RULED_TABLE_OCR,
                fallback=RegionAction.VLM_TABLE,
            ),
            target_block=None,
            out_dir=tmp_path / "out",
            assets_dir=tmp_path / "out" / "assets",
            lang="vie",
            render_cache=cache,
            scheduler=AdaptiveScheduler(),
            telemetry={"ocr_calls": 0},
            region_timeout_seconds=10.0,
            vl_reader=FailingVL(),
            inc_ocr_calls=lambda d, n: None,
            force_vlm=True,
        )
    finally:
        cache.close()
    tbl_blk = tbl_page["blocks"][0]
    assert "boom table read" in tbl_blk["structured_provenance"]["error"]

