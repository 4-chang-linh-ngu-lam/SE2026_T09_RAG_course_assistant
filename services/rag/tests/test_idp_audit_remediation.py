"""Regression tests covering all 8 IDP audit remediation items."""

from __future__ import annotations

import ast
import io
import json
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw
import pytest

from idp import publish as idp_publish
from idp.backends.layout import detect_missed_ink_regions
from idp.backends.native.office import (
    csv_pages,
    decode_txt,
    email_pages,
    extract_office_pages,
    html_pages,
    md_pages,
    pptx_pages,
    txt_pages,
    xlsx_pages,
)
from idp.backends.native.registry import NativeParseResult, NativeParserRegistry, default_native_parser_registry
from idp.config import GENERAL, MATH_VI, ParseConfig, RenderConfig, detect_math_profile
from idp.evidence.fusion import RegionEnricher, enrichment_summary, fuse_vl_regions, regions, vl_reread_page
from idp.evidence.recovery import RecoveryOptions
from idp.ingest import ingest_file
from idp.input.profiler import PageProfile, profile_pdf_page
from idp.input.validation import InputError
from idp.pipeline.native_escalation import vlm_read_native_blocks
from idp.pipeline.ocr_executor import execute_ruled_table_task, run_scan_page_with_retry, vlm_structured_ocr_tasks
from idp.pipeline.page_router import PageDecision, PageRoute, PageRouter
from idp.pipeline.region_router import RegionAction, RegionRouter, RegionTask
from idp.pipeline.reporting import maybe_upgrade_auto_profile
from idp.pipeline.scheduler import AdaptiveScheduler, ModelPool
from idp.processing.render import PageRenderCache
from idp.runtime.compatibility import probe_runtime, runtime_manifest
from idp.serving.client import CircuitOpenError, LocalRegionError, ModelOriginPolicy, ServingCircuitBreaker
from idp.validation.calibration import (
    CalibrationRegistry,
    IsotonicCalibrator,
    PlattCalibrator,
    build_confidence_meta,
    expected_calibration_error,
)
from idp.validation.quality_gate import audit_canonical

RAG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = RAG_ROOT.parents[1]


# ---------------------------------------------------------------------------
# 1. VLM token logprobs confidence & structured region OCR
# ---------------------------------------------------------------------------


def test_vlm_read_native_blocks_extracts_token_logprob_confidence(tmp_path):
    pdf_path = tmp_path / "native.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((40, 60), "Giai phuong trinh")
    doc.save(pdf_path)
    doc.close()

    cache = PageRenderCache(pdf_path, tmp_path / "render", RenderConfig(base_dpi=150))
    try:
        scheduler = AdaptiveScheduler()
        block = {
            "block_id": "p0001_b001",
            "block_type": "Text",
            "bbox": [30.0, 40.0, 260.0, 90.0],
            "text": "Giai phuong trinh",
            "source": "pymupdf",
            "confidence": None,
            "review_flags": [{"code": "TEXT_ENCODING_REVIEW", "severity": "warning"}],
        }
        page_dict = {"page_id": 1, "page_size": [400, 200], "blocks": [block], "review": []}

        class _LogprobVLReader:
            def __call__(self, image, kind):
                return [
                    ("Giải", 0.97, []),
                    (" phương", 0.96, []),
                    (" trình", 0.95, []),
                ]

        vlm_read_native_blocks(
            page_dict,
            [block],
            RegionAction.VLM_TEXT,
            tmp_path / "out",
            cache,
            scheduler,
            "general",
            vl_reader=_LogprobVLReader(),
            region_timeout_seconds=10.0,
        )
        assert block["text"] == "Giải phương trình"
        assert block["confidence"] == 0.95
        assert block["confidence_meta"]["score_kind"] == "vlm_min_token_prob"
        assert block["confidence_meta"]["is_calibrated"] is False
        assert not any(f["code"] == "VLM_UNSCORED_REVIEW" for f in block["review_flags"])
    finally:
        cache.close()


def test_vlm_structured_ocr_tasks_handles_text_table_and_formula_validation(tmp_path):
    img_path = tmp_path / "scan.png"
    Image.new("RGB", (600, 800), "white").save(img_path)
    cache = PageRenderCache(None, tmp_path / "render", precomputed_images={1: img_path})
    try:
        scheduler = AdaptiveScheduler()
        page_dict = {
            "page_id": 1,
            "page_size": [600, 800],
            "blocks": [
                {"block_id": "p0001_ocr1", "block_type": "Text", "bbox": [20, 20, 300, 80], "text": "old"}
            ],
            "review": [],
        }

        class _StructuredReader:
            def read_region_structured(self, crop_path, kind, timeout=10.0):
                if kind == "Text":
                    return {"text": "Đoạn văn bản đã đọc"}
                if kind == "Table":
                    return {"table_html": "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"}
                if kind == "Equation":
                    return {"latex": r"$\frac{1}{2$"}  # intentionally unbalanced brace
                return {}

        tasks = [
            RegionTask(
                region_id="r_text",
                kind="Text",
                bbox=[20, 20, 300, 80],
                action=RegionAction.VLM_TEXT,
                source_block_ids=["p0001_ocr1"],
            ),
            RegionTask(
                region_id="r_table",
                kind="Table",
                bbox=[20, 100, 300, 260],
                action=RegionAction.VLM_TABLE,
            ),
            RegionTask(
                region_id="r_eq",
                kind="Equation",
                bbox=[20, 280, 300, 360],
                action=RegionAction.VLM_FORMULA,
            ),
        ]
        vlm_structured_ocr_tasks(
            page_dict,
            tasks,
            tmp_path / "out",
            cache,
            scheduler,
            vl_reader=_StructuredReader(),
            region_timeout_seconds=10.0,
        )
        ids = {b["block_id"] for b in page_dict["blocks"]}
        assert "p0001_ocr1" not in ids
        assert {"p0001_r_text", "p0001_r_table", "p0001_r_eq"} <= ids

        eq = next(b for b in page_dict["blocks"] if b["block_id"] == "p0001_r_eq")
        assert eq["latex_validation"][0]["valid"] is False
        assert any(f["code"] == "LATEX_INVALID" for f in eq["review_flags"])

        tbl = next(b for b in page_dict["blocks"] if b["block_id"] == "p0001_r_table")
        assert tbl["table_shape"] == [2, 2]
        assert tbl["confidence"] is None
        assert tbl["confidence_meta"]["is_calibrated"] is False
    finally:
        cache.close()


def test_fuse_vl_regions_runs_real_latex_validation():
    page = {"page_id": 1, "page_size": [600, 800], "blocks": []}
    regs = [("Equation", (10.0, 10.0, 200.0, 80.0), [])]
    reads = [([("x", 0.99, []), ("^", 0.98, []), ("{", 0.97, []), ("2", 0.99, [])], None)]
    fuse_vl_regions(page, regs, reads)
    eq = page["blocks"][0]
    assert eq["latex_validation"][0]["valid"] is False
    assert any(f["code"] == "LATEX_INVALID" for f in eq["review_flags"])
    assert eq["confidence_meta"]["score_kind"] == "vlm_min_token_prob"


# ---------------------------------------------------------------------------
# 2. Canonical v1/v2 unification & idp.publish
# ---------------------------------------------------------------------------


def test_canonical_v1_and_v2_unification_preserves_bare_legacy_citations():
    sha = "a" * 64
    v1_doc = {
        "schema_version": "idp-canonical-1",
        "source_sha256": sha,
        "pages": [
            {
                "page_id": 1,
                "page_route": "SCAN_FAST_OCR",
                "blocks": [
                    {
                        "block_id": "p0001_b001",
                        "block_type": "Text",
                        "text": "Định lí Pytago",
                        "source": "pymupdf",
                        "confidence": None,
                    }
                ],
            }
        ],
    }
    normalized = idp_publish.normalize_canonical(v1_doc)
    assert normalized["document_version"] == f"sha256:{sha}"
    blk = normalized["pages"][0]["blocks"][0]
    assert blk["provenance"]["version"] == idp_publish.PROVENANCE_VERSION
    assert blk["provenance"]["region_id"] is None
    assert blk["provenance"]["evidence_refs"] == []
    assert normalized["pages"][0]["page_route"] == "SCAN_FAST_OCR"

    audit = audit_canonical(normalized)
    assert audit["quality"]["confidence_calibrated"] is False
    assert audit["quality"]["confidence_semantics"] == "deterministic_native_no_ocr_score"

    v2_ocr = {
        "schema_version": "idp-canonical-2",
        "source_sha256": sha,
        "pages": [
            {
                "page_id": 1,
                "blocks": [
                    {
                        "block_id": "p0001_b001",
                        "block_type": "Text",
                        "text": "Định lí Pytago",
                        "source": "tesseract",
                        "confidence": 0.88,
                    }
                ],
            }
        ],
    }
    norm_v2 = idp_publish.normalize_canonical(v2_ocr)
    audit_v2 = audit_canonical(norm_v2)
    assert audit_v2["quality"]["confidence_calibrated"] is False
    assert audit_v2["quality"]["confidence_semantics"] == "uncalibrated_heuristic_routing_score"


def test_ingest_file_emits_runtime_manifest_and_unified_provenance(tmp_path):
    pdf_path = tmp_path / "clean.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 80), "Tai lieu mon Lich su Viet Nam danh cho hoc sinh pho thong nam 2026.")
    doc.save(pdf_path)
    doc.close()

    out_dir = tmp_path / "out"
    result = ingest_file(pdf_path, out_dir)
    canonical = json.loads((out_dir / "canonical.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert canonical["schema_version"] == "idp-canonical-1"
    assert canonical["canonical_contract_version"] == idp_publish.CANONICAL_CONTRACT_VERSION
    assert canonical["provenance_version"] == idp_publish.PROVENANCE_VERSION
    assert canonical["document_version"].startswith("sha256:")
    assert canonical["runtime_manifest"]["schema_version"] == "idp-runtime-compat-1"
    assert report["runtime_manifest"]["schema_version"] == "idp-runtime-compat-1"
    assert result["ingestion_auto_publish_pass"] is True


# ---------------------------------------------------------------------------
# 3. Pluggable NativeParserRegistry & clean splits
# ---------------------------------------------------------------------------


def test_native_parser_registry_and_legacy_facade_exports(tmp_path):
    reg = default_native_parser_registry()
    for expected in ("docx", "text", "markdown", "html", "csv", "xlsx", "pptx", "email"):
        assert reg.has(expected)

    custom = NativeParserRegistry()
    custom.register(
        "custom_fmt",
        lambda src, assets, *, profile_name="general", options=None: NativeParseResult(
            pages=[{"page_id": 1, "blocks": [], "profile": profile_name}],
            source_type="custom",
        ),
    )
    sample = tmp_path / "x.custom"
    sample.write_text("hi", encoding="utf-8")
    parsed = custom.parse("custom_fmt", sample, tmp_path / "assets", profile_name="math_vi")
    assert parsed.source_type == "custom"
    assert parsed.pages[0]["profile"] == "math_vi"

    # Facade exports remain callable/importable without circular imports
    assert callable(extract_office_pages)
    assert callable(txt_pages)
    assert callable(md_pages)
    assert callable(html_pages)
    assert callable(csv_pages)
    assert callable(xlsx_pages)
    assert callable(pptx_pages)
    assert callable(email_pages)
    assert callable(decode_txt)
    assert callable(regions) and callable(vl_reread_page) and callable(enrichment_summary)
    assert RegionEnricher is not None

    bench_ast = ast.parse((RAG_ROOT / "tools" / "benchmark_idp.py").read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(bench_ast)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "idp.documents.digital" not in imported


# ---------------------------------------------------------------------------
# 4. Heuristic routing fixes, missed-ink recovery & retry DPI
# ---------------------------------------------------------------------------


def test_scan_with_header_trap_and_vector_risk_escalate_to_ocr(tmp_path):
    pdf_path = tmp_path / "scan_with_header.pdf"
    scan_img = Image.new("RGB", (600, 800), "white")
    buf = io.BytesIO()
    scan_img.save(buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(10, 50, 590, 790), stream=buf.getvalue())
    page.insert_text((30, 30), "Truong THPT Nguyen Trai - De kiem tra Toan lop 12")
    doc.save(pdf_path)
    doc.close()

    with fitz.open(pdf_path) as opened:
        profile = profile_pdf_page(opened[0], 1)

    assert "scan_with_header_large_image" in profile.routing_signals
    decision = PageRouter().route_page(profile, has_layout=True, has_vlm=True)
    assert decision.route == PageRoute.SCAN_LAYOUT_HYBRID
    assert decision.ocr_required is True
    assert "scan_with_header_large_image" in decision.reasons
    assert decision.risk_score >= 0.70

    vector_profile = PageProfile(
        page_id=2,
        width=600,
        height=800,
        rotation=0,
        char_count=75,
        word_count=12,
        letter_ratio=0.80,
        text_block_count=1,
        garbled_block_count=0,
        garbled_block_ratio=0.0,
        has_encoding_issues=False,
        encoding_issue_codes=[],
        garbled=False,
        repeated_url_only=False,
        scan_noise=False,
        ocr_reason=None,
        math_font_spans=0,
        math_char_count=0,
        math_ratio=0.0,
        has_fragment_math=False,
        has_table_grid=False,
        drawing_count=320,
        image_count=0,
        image_area_ratio=0.0,
        max_single_image_ratio=0.0,
        is_multi_column_native=False,
        is_toc=False,
        blank=False,
        text_area_ratio=0.02,
        uncovered_image_ratio=0.0,
        vector_text_risk=True,
        routing_risk_score=0.5,
    )
    vec_decision = PageRouter().route_page(vector_profile, has_layout=False, has_vlm=False)
    assert vec_decision.route == PageRoute.SCAN_FAST_OCR
    assert "vector_outlined_text_risk" in vec_decision.reasons


def test_region_router_tightens_early_exit_on_degraded_preprocessing_and_column_split():
    router = RegionRouter()
    base_page = {
        "page_size": [1200, 1600],
        "blocks": [
            {"block_id": "b1", "block_type": "Text", "bbox": [50, 100, 480, 124], "text": "Dong van ban sach.", "confidence": 0.86},
            {"block_id": "b2", "block_type": "Text", "bbox": [700, 100, 1120, 124], "text": "Cot thu hai doc lap.", "confidence": 0.86},
        ],
    }
    clean_tasks = router.route_ocr_page_regions(base_page, None, has_vlm=True, image_size=(1200, 1600))
    assert len(clean_tasks) == 2
    assert all(t.action == RegionAction.NATIVE_KEEP for t in clean_tasks)

    blurry_page = {**base_page, "preprocessing": {"blurry": True}}
    degraded_tasks = router.route_ocr_page_regions(blurry_page, None, has_vlm=True, image_size=(1200, 1600))
    assert all(t.action == RegionAction.VLM_TEXT for t in degraded_tasks)
    assert all("degraded_scan_image" in t.reasons for t in degraded_tasks)


def test_detect_missed_ink_regions_finds_uncovered_ink_block(tmp_path):
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 220, 75], fill="black")  # covered by existing OCR line
    draw.text((80, 220), "MISSED REGION CONTENT", fill="black")
    draw.rectangle([70, 215, 340, 250], fill="black")
    img_path = tmp_path / "ink.png"
    img.save(img_path)

    missed = detect_missed_ink_regions(
        img_path,
        [{"bbox": [35, 35, 225, 80], "text": "Covered"}],
    )
    assert any(box[1] >= 180 and box[3] <= 300 for item in missed for box in [item["bbox"]])


def test_run_scan_page_with_retry_rerenders_at_retry_dpi(tmp_path):
    pdf_path = tmp_path / "low_conf.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((40, 100), "Noi dung can doc lai o DPI cao hon")
    doc.save(pdf_path)
    doc.close()

    out_dir = tmp_path / "out"
    cache = PageRenderCache(pdf_path, tmp_path / "render", RenderConfig(base_dpi=150))
    calls: list[int] = []

    def fake_ocr(image_path, ocr_dir, pid, *, lang, profile):
        with Image.open(image_path) as opened:
            calls.append(opened.width)
        conf = 42.0 if len(calls) == 1 else 94.0
        return [{"text": "Nội dung rõ nét", "confidence": conf, "bbox": [20, 40, 200, 60]}]

    try:
        cfg = ParseConfig()
        decision = PageDecision(
            page_id=1,
            route=PageRoute.SCAN_FAST_OCR,
            level=1,
            render_required=True,
            ocr_required=True,
        )
        result = run_scan_page_with_retry(
            decision,
            profile_width=400.0,
            profile_height=500.0,
            ocr_reason=None,
            out_dir=out_dir,
            assets_dir=out_dir / "assets",
            lang="vie",
            profile_name="general",
            render_cache=cache,
            scheduler=AdaptiveScheduler(),
            telemetry={"ocr_calls": 0, "region_actions": {}, "vlm_skipped_early_exit": 0, "vlm_budget_skipped": 0},
            config=cfg,
            detector=None,
            vl_reader=None,
            region_enricher=None,
            dual_reader=None,
            region_router=RegionRouter(cfg.router),
            recovery_options=RecoveryOptions(),
            has_vlm=False,
            record_task_telemetry=lambda *_a: None,
            inc_ocr_calls=lambda tel, n=1: tel.__setitem__("ocr_calls", tel["ocr_calls"] + n),
            ocr_page_image_fn=fake_ocr,
            detect_panels_fn=lambda *_a: [],
        )
        assert len(calls) == 2
        assert result["render_provenance"]["dpi"] == cfg.render.retry_dpi
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# 5. Math profile default & SGK accuracy without false positives
# ---------------------------------------------------------------------------


def test_math_profile_defaults_to_auto_and_upgrades_sgk_math_post_ocr():
    assert ParseConfig().profile == "auto"
    assert detect_math_profile("a-b") is GENERAL
    assert detect_math_profile("2026-11-24 e-learning pre-commit") is GENERAL
    sgk = (
        "Cho tam giác ABC vuông tại A, chứng minh định lý với phân số 3/4 "
        "và tìm nghiệm đa thức phương trình bậc hai."
    )
    assert detect_math_profile(sgk) is MATH_VI

    pages = [
        {
            "page_id": 1,
            "profile": "general",
            "blocks": [
                {
                    "block_id": "p0001_b1",
                    "block_type": "Text",
                    "text": sgk,
                    "markdown": sgk,
                }
            ],
        }
    ]
    upgraded = maybe_upgrade_auto_profile(
        pages,
        requested_profile="auto",
        current_profile=GENERAL,
    )
    assert upgraded is MATH_VI
    assert pages[0]["profile"] == "math_vi"


# ---------------------------------------------------------------------------
# 6. Model serving isolation, allowlist, auth & circuit breaker
# ---------------------------------------------------------------------------


def test_serving_policy_circuit_breaker_and_remote_mode_guard(tmp_path):
    with pytest.raises(LocalRegionError, match="loopback"):
        ModelOriginPolicy().validate("http://vlm-serving:8081")

    ModelOriginPolicy(allowed_hosts=("vlm-serving",)).validate("http://vlm-serving:8081")
    with pytest.raises(LocalRegionError, match="outside loopback"):
        ModelOriginPolicy(allowed_hosts=("vlm-serving",)).validate("http://untrusted:8081")

    breaker = ServingCircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    assert breaker.allow_request() is True
    breaker.record_failure("timeout")
    assert breaker.state()["status"] == "closed"
    breaker.record_failure("timeout")
    assert breaker.state()["status"] == "open"
    assert breaker.allow_request() is False
    assert breaker.state()["total_short_circuits"] == 1
    breaker.record_success()
    assert breaker.state()["status"] == "closed"

    with pytest.raises(InputError) as exc_info:
        ModelPool().get_layout_detector(tmp_path, serving_mode="remote")
    assert exc_info.value.code == "MODEL_SERVING_REMOTE_ONLY"


class _InMemorySocket:
    def __init__(self, raw_request: bytes) -> None:
        self._rfile = io.BytesIO(raw_request)
        self._wfile = io.BytesIO()

    def makefile(self, mode: str, *_args, **_kwargs):
        return self._rfile if "r" in mode else self._wfile

    def setsockopt(self, *_args) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self._wfile.write(data)

    def close(self) -> None:
        pass


def _dispatch_http(server, raw_request: bytes) -> tuple[int, dict]:
    sock = _InMemorySocket(raw_request)
    server.RequestHandlerClass(sock, ("127.0.0.1", 50000), server)
    raw_resp = sock._wfile.getvalue().decode("utf-8")
    head, _, body = raw_resp.partition("\r\n\r\n")
    status = int(head.splitlines()[0].split()[1])
    return status, json.loads(body)


def test_gpu_layout_server_enforces_service_key_and_exposes_metrics():
    from tools.gpu_layout_server import create_server

    class _FakeBackend:
        revision = "test-rev"
        identity = {"name": "FakeLayout", "revision": "test-rev"}

        def health(self):
            return {"status": "ok"}

        def predict_image_bytes(self, _raw):
            return [{"bbox": [1.0, 2.0, 30.0, 40.0], "kind": "text", "layout_score": 0.99}]

    server = create_server("127.0.0.1", 0, _FakeBackend(), service_key="top-secret-key")
    try:
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
        payload = json.dumps({"image_base64": __import__("base64").b64encode(buf.getvalue()).decode()}).encode()

        unauth_req = (
            b"POST /v1/layout HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        status, _ = _dispatch_http(server, unauth_req)
        assert status == 401

        auth_req = (
            b"POST /v1/layout HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            + b"X-Model-Service-Key: top-secret-key\r\n"
            + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        status, body = _dispatch_http(server, auth_req)
        assert status == 200
        assert len(body["boxes"]) == 1

        metrics_req = b"GET /metrics HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        status, metrics = _dispatch_http(server, metrics_req)
        assert status == 200
        assert metrics["requests"] == 1
        assert metrics["unauthorized"] == 1
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# 7. External runtime compatibility probe & bounded dependency versions
# ---------------------------------------------------------------------------


def test_runtime_compatibility_probe_detects_broken_tessdata_and_bounded_toml(monkeypatch):
    monkeypatch.setenv("TESSDATA_PREFIX", "/nonexistent/tessdata/dir")
    monkeypatch.setattr("shutil.which", lambda name: None if name != "tesseract" else "tesseract")
    report = probe_runtime(include_external_binaries=True, force_refresh=True)
    assert report["schema_version"] == "idp-runtime-compat-1"
    assert report["packages"]["pymupdf"]["compatible"] is True
    assert any("TESSDATA_PREFIX" in w for w in report["warnings"])

    manifest = runtime_manifest(include_external_binaries=False)
    assert manifest["schema_version"] == "idp-runtime-compat-1"
    assert "pymupdf" in manifest["packages"]

    doc_pyproject_path = REPO_ROOT / "services" / "document" / "pyproject.toml"
    if doc_pyproject_path.is_file():
        doc_pyproject = tomllib.loads(doc_pyproject_path.read_text(encoding="utf-8"))
        deps = doc_pyproject["project"]["dependencies"]
        bounded_targets = ("pymupdf", "pillow", "pdfplumber", "numpy", "opencv-python-headless", "pypandoc-binary")
        for target in bounded_targets:
            matched = [d for d in deps if d.lower().startswith(target.lower())]
            assert matched and "<" in matched[0], f"{target} must have an upper version bound in dependencies"


# ---------------------------------------------------------------------------
# 8. Confidence semantics & calibration accuracy
# ---------------------------------------------------------------------------


def test_ruled_table_fallback_does_not_fabricate_numeric_confidence(tmp_path):
    img_path = tmp_path / "tbl.png"
    Image.new("RGB", (400, 300), "white").save(img_path)
    cache = PageRenderCache(None, tmp_path / "render", precomputed_images={1: img_path})
    try:
        page = {"page_id": 1, "page_size": [400, 300], "blocks": [], "review": []}

        class _VlmTableOnly:
            def read_region_structured(self, crop, kind, timeout=10.0):
                return {"table_html": "<table><tr><td>1</td><td>2</td></tr></table>"}

        execute_ruled_table_task(
            page,
            RegionTask(region_id="tbl1", kind="Table", bbox=[10, 10, 390, 290], action=RegionAction.RULED_TABLE_OCR),
            target_block=None,
            out_dir=tmp_path / "out",
            assets_dir=tmp_path / "out" / "assets",
            lang="vie",
            render_cache=cache,
            scheduler=AdaptiveScheduler(),
            telemetry={"ocr_calls": 0},
            region_timeout_seconds=10.0,
            vl_reader=_VlmTableOnly(),
            inc_ocr_calls=lambda tel, n=1: tel.__setitem__("ocr_calls", tel["ocr_calls"] + n),
            force_vlm=True,
        )
        blk = page["blocks"][0]
        assert blk["confidence"] is None
        assert blk["confidence_meta"]["is_calibrated"] is False
        assert blk["confidence_meta"]["score_kind"] == "vlm_unscored"
    finally:
        cache.close()


def test_calibration_metrics_and_calibrator_fitting_roundtrip():
    rng = np.random.default_rng(7)
    raw_scores = [float(x) for x in np.clip(rng.uniform(0.55, 0.99, size=120), 0.05, 0.99)]
    # Make probabilities systematically overconfident (~0.55..0.85 true accuracy)
    labels = [bool(rng.random() < (0.35 + 0.45 * s)) for s in raw_scores]

    raw_ece = expected_calibration_error(raw_scores, labels, n_bins=10)
    assert raw_ece["overconfidence_gap"] > 0.0

    platt = PlattCalibrator.fit(raw_scores, labels, min_samples=30, max_verified_ece=0.15)
    iso = IsotonicCalibrator.fit(raw_scores, labels, min_samples=30, max_verified_ece=0.15)
    assert platt.metrics["post_fit"]["ece"] <= raw_ece["ece"]
    assert iso.metrics["post_fit"]["ece"] <= raw_ece["ece"]

    reg = CalibrationRegistry()
    reg.register(platt, source="tesseract", score_kind="tesseract_word_heuristic", profile="auto")
    restored = CalibrationRegistry.from_dict(reg.to_dict())
    active = restored.get(source="tesseract", score_kind="tesseract_word_heuristic", profile="auto")
    assert active is not None and active.verified is True

    cal_meta = build_confidence_meta(0.90, source="tesseract", calibrator=active)
    assert cal_meta["is_calibrated"] is True
    assert cal_meta["calibrated_probability"] is not None

    unverified = PlattCalibrator(a=1.0, b=0.0, verified=False)
    unverified_meta = build_confidence_meta(0.90, source="tesseract", calibrator=unverified)
    assert unverified_meta["is_calibrated"] is False
    assert unverified_meta["calibrated_probability"] is None


# ---------------------------------------------------------------------------
# 9. Remote throughput optimizations (keep-alive, JPEG layout, batching)
# ---------------------------------------------------------------------------


def test_post_json_keepalive_reuses_connection_retries_stale_and_rejects_redirects(monkeypatch):
    import base64
    import http.client
    from idp.backends.layout import RemoteLayoutDetector
    from idp.pipeline.orchestrator import AdaptiveHybridOrchestrator
    from idp.serving import client as serving_client

    created: list[object] = []
    serving_client._THREAD_LOCAL_CONNS.conns = {}
    behaviors = [
        ("ok", 200, b'{"ok": 1}'),
        ("ok", 200, b'{"ok": 2}'),
        ("stale_once", 200, b'{"ok": 3}'),
        ("ok", 302, b""),
    ]

    class _FakeResp:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self.reason = "OK" if status == 200 else "Found"
            self.headers = {"Connection": "keep-alive"}
            self._body = body

        def read(self, _n: int = -1) -> bytes:
            return self._body

    class _FakeHTTPConnection:
        def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.sock = None
            self.closed = False
            self._next: tuple[int, bytes] | None = None
            created.append(self)

        def request(self, _method: str, _path: str, body: bytes = b"", headers: dict | None = None) -> None:
            assert headers and headers.get("Connection") == "keep-alive"
            mode, status, payload = behaviors.pop(0)
            if mode == "stale_once":
                raise http.client.RemoteDisconnected("stale keep-alive socket")
            self._next = (status, payload)

        def getresponse(self) -> _FakeResp:
            assert self._next is not None
            return _FakeResp(*self._next)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(serving_client.http.client, "HTTPConnection", _FakeHTTPConnection)

    r1 = serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    r2 = serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    assert r1 == b'{"ok": 1}'
    assert r2 == b'{"ok": 2}'
    assert len(created) == 1  # Connection reused!

    # Inject next ok response after the stale disconnect retry
    behaviors.insert(1, ("ok", 200, b'{"ok": 3}'))
    r3 = serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    assert r3 == b'{"ok": 3}'
    assert len(created) == 2

    with pytest.raises(LocalRegionError) as exc_info:
        serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    assert exc_info.value.code == "ORIGIN"

    # JPEG layout encoding & downscale
    img_path = Path(REPO_ROOT / "services" / "rag")  # not written; use tempfile
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "big.png"
        Image.new("RGB", (600, 600), "white").save(png)
        det = RemoteLayoutDetector("http://127.0.0.1:8112", max_pixels=90_000)
        b64, sx, sy, mime = det._encode_image(png)
        assert mime == "image/jpeg"
        assert sx > 1.0 and sy > 1.0
        assert base64.b64decode(b64)[:2] == b"\xff\xd8"

        captured: dict = {}

        def fake_run(self, *_a, **_kw):
            captured["cpu_workers"] = self.config.execution.cpu_workers
            captured["page_batch_size"] = self.config.execution.page_batch_size
            return {"ok": True}

        monkeypatch.setattr(AdaptiveHybridOrchestrator, "run", fake_run)
        ingest_file(png, Path(td) / "out", workers=6, page_batch_size=12)
        assert captured == {"cpu_workers": 6, "page_batch_size": 12}


def test_post_json_keepalive_retries_connection_aborted_on_reused_socket(monkeypatch):
    import http.client
    from idp.serving import client as serving_client

    serving_client._THREAD_LOCAL_CONNS.conns = {}
    created: list[object] = []
    outcomes = [
        ("ok", b'{"ok": 1}'),
        ("aborted", b""),
        ("ok", b'{"ok": 2}'),
    ]

    class _Resp:
        def __init__(self, body: bytes) -> None:
            self.status = 200
            self.reason = "OK"
            self.headers = {"Connection": "keep-alive"}
            self._body = body

        def read(self, _n: int = -1) -> bytes:
            return self._body

    class _Conn:
        def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
            self.sock = None
            self.timeout = timeout
            self._body = b""
            created.append(self)

        def request(self, _method: str, _path: str, body: bytes = b"", headers: dict | None = None) -> None:
            kind, payload = outcomes.pop(0)
            if kind == "aborted":
                raise ConnectionAbortedError(10053, "WinError 10053 connection aborted")
            self._body = payload

        def getresponse(self) -> _Resp:
            return _Resp(self._body)

        def close(self) -> None:
            pass

    monkeypatch.setattr(serving_client.http.client, "HTTPConnection", _Conn)
    r1 = serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    r2 = serving_client.post_json_keepalive("http://127.0.0.1:8111/v1/chat/completions", b"{}", {}, timeout=5.0, max_bytes=1024)
    assert r1 == b'{"ok": 1}'
    assert r2 == b'{"ok": 2}'
    assert len(created) == 2

