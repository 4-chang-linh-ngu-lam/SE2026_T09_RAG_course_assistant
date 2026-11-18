"""Phase 3: real PDF, real OCR, publication and shadow isolation."""

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic

import fitz
import pytest
from idp.pdf.profiling import PageSignals, RegionSignal, profile_pages
from idp.pdf.router import PageRoute, PdfRouter, RoutingPolicy
from idp.pdf.service import DeepDocConfig, DeepDocService

FIX = Path(__file__).parent / "fixtures/generated"
REAL_OCR = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="real Tesseract executable required"
)


def signal(**changes):
    base = PageSignals(1, 400, 600, 100, 2, 0.1, 0, None, 0.8, 0, False, False, False)
    return replace(base, **changes)


REGION = RegionSignal((10, 10, 100, 30), "SUSPECT", "region:test")


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes,options,expected",
    [
        ({}, {}, "native_only"),
        ({"math_signal": True}, {}, "native_only"),
        ({"structure_signal": True}, {}, "native_only"),
        ({"char_count": 0, "block_count": 0, "image_count": 1}, {}, "ocr_page"),
        ({"char_count": 0, "blank_confirmed": True}, {}, "blank"),
        ({"char_count": 0, "blank_confirmed": None}, {}, "ocr_page"),
        ({"char_count": 0, "blank_confirmed": False}, {}, "ocr_page"),
        ({"blank_confirmed": True}, {}, "review"),
        ({"glyph_suspect": True}, {}, "review"),
        ({"encoding_suspect": True}, {}, "review"),
        ({"glyph_suspect": True, "regions": (REGION,)}, {}, "native_plus_region_ocr"),
        (
            {"encoding_suspect": True, "regions": (REGION,)},
            {},
            "native_plus_region_ocr",
        ),
        ({"image_count": 1, "regions": (REGION,)}, {}, "native_plus_region_ocr"),
        ({"image_count": 1}, {}, "review"),
        ({"image_count": 1, "image_coverage": 0.9, "char_count": 0}, {}, "ocr_page"),
        ({"garbled_ratio": 0.4}, {}, "ocr_page"),
        ({"garbled_ratio": 0.3}, {}, "native_only"),
        ({"repeated_noise": True}, {}, "ocr_page"),
        ({"hidden_layer_suspect": True}, {}, "ocr_page"),
        ({"hidden_layer_suspect": None}, {}, "native_only"),
        ({"char_count": 2, "letter_ratio": 0.1}, {}, "review"),
        (
            {"char_count": 2, "letter_ratio": 0.1, "math_signal": True},
            {},
            "native_only",
        ),
        ({}, {"force_ocr": True}, "ocr_page"),
        ({}, {"force_ocr": True, "ocr_available": False}, "review"),
        ({"char_count": 0}, {"ocr_available": False}, "review"),
        # pdf-routing:2 keeps native text when only region OCR is missing
        # (audit IDP-006); pdf-routing:1 sent the whole page to review.
        ({"regions": (REGION,)}, {"ocr_available": False}, "native_only"),
        ({}, {"ocr_available": False}, "native_only"),
        (
            {"regions": (REGION, replace(REGION, bbox=(200, 200, 300, 230)))},
            {},
            "native_plus_region_ocr",
        ),
        (
            {"regions": (RegionSignal((0, 0, 400, 600), "IMAGE"),)},
            {},
            "native_plus_region_ocr",
        ),
    ],
)
def test_route_table(changes, options, expected):
    item = signal(**changes)
    router = PdfRouter()
    plan = router.route("0" * 64, (item,), **options)
    assert plan.pages[0].route.value == expected
    assert plan.pages[0].signals == item
    assert plan == router.route("0" * 64, (item,), **options)
    assert plan.policy_sha256 == RoutingPolicy().fingerprint


@pytest.mark.unit
def test_routing_v1_keeps_whole_page_review_without_region_ocr():
    item = signal(regions=(REGION,))
    legacy = PdfRouter(RoutingPolicy(version="pdf-routing:1"))
    plan = legacy.route("0" * 64, (item,), ocr_available=False)
    assert plan.pages[0].route.value == "review"
    assert plan.pages[0].reasons == ("OCR_BACKEND_UNAVAILABLE",)
    current = PdfRouter().route("0" * 64, (item,), ocr_available=False).pages[0]
    assert current.reasons == ("SUSPECT_OR_IMAGE_REGIONS", "REGION_OCR_UNAVAILABLE")
    assert current.regions == (REGION,)


def test_bad_route_geometry():
    with pytest.raises(ValueError):
        PdfRouter().route(
            "0" * 64, (signal(regions=(RegionSignal((-1, 0, 40, 80), "bad"),)),)
        )


@pytest.mark.integration
def test_native_no_ocr(tmp_path, monkeypatch):
    import idp.pdf.service as module
    from idp.evidence.serde import load

    def forbidden(*args, **kwargs):
        raise AssertionError("good native pages must not call/render OCR")

    monkeypatch.setattr(module, "TesseractBackend", forbidden)
    monkeypatch.setattr(module, "render_page", forbidden)
    output = DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
        FIX / "native.pdf", tmp_path
    )
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["ocr_invocations"] == 0
    assert output["schema_version"] == "idp-canonical-1"
    assert "Independent expected text" in " ".join(
        b["text"] for p in output["pages"] for b in p["blocks"]
    )
    record = load((tmp_path / "extraction.json").read_text())
    assert all(o.extraction is not None for o in record.observations)
    from idp.validation.ingestion_checks import check_ingestion_artifacts

    assert check_ingestion_artifacts(tmp_path, [1])["pass"] is True


@REAL_OCR
@pytest.mark.integration
@pytest.mark.parametrize("name,ocr_pages", [("scan.pdf", [1]), ("mixed.pdf", [2])])
def test_real_pdf_ocr_e2e(tmp_path, name, ocr_pages):
    from idp.evidence.serde import load

    output = DeepDocService(
        DeepDocConfig(engine="unified", language="eng")
    ).process_pdf(FIX / name, tmp_path)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["ocr_pages"] == ocr_pages
    assert report["ocr_invocations"] == len(ocr_pages)
    text = " ".join(b["text"] for p in output["pages"] for b in p["blocks"])
    assert "Native source evidence for regression." in text
    record = load((tmp_path / "extraction.json").read_text())
    ocr = [o for o in record.observations if o.extraction_source.value == "OCR"]
    assert ocr and all(o.locations[0].page in ocr_pages for o in ocr)
    assert all(0 <= o.attributes["recognition"]["confidence"] <= 1 for o in ocr)
    assert all(o.locations[0].bbox.x1 > o.locations[0].bbox.x0 for o in ocr)
    assert report["provenance_coverage"] == 1
    assert list((tmp_path / "ocr_raw").glob("*.tsv"))
    assert [p["page_number"] for p in output["pages"]] == list(
        range(1, len(output["pages"]) + 1)
    )
    if name == "mixed.pdf":
        assert output["pages"][0]["classification"] == "native_only"


def spanning_table():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for row in range(4):
        page.insert_text((40, 80 + row * 20), f"LEFT INTRO {row}")
        page.insert_text((340, 80 + row * 20), f"RIGHT INTRO {row}")
    for y in (190, 220, 250):
        page.draw_line((40, y), (560, y))
    for x in (40, 210, 390, 560):
        page.draw_line((x, 190), (x, 250))
    for x, word in ((50, "Name"), (220, "Value"), (400, "Grade")):
        page.insert_text((x, 210), word)
    page.insert_text((40, 350), "AFTERLEFT")
    page.insert_text((340, 350), "AFTERRIGHT")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.integration
def test_integrated_w1():
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.layout import PdfLayoutPolicy
    from parser.pdf.engine import PdfParsingEngine as OriginalEngine

    data = spanning_table()
    original = OriginalEngine().extract_source(data)
    engine = PdfParsingEngine()
    native = engine.extract_native(data)
    result = engine.finalize(
        native, layout_policy=PdfLayoutPolicy(version="pdf-layout:2")
    )
    text = "\n".join(o.text or "" for o in result.observations)
    assert text.index("Grade") < text.index("AFTERLEFT") < text.index("AFTERRIGHT")
    before = {
        o.source_id: (
            o.text,
            tuple(asdict(loc) for loc in o.locations),
            o.extraction.raw_candidate_id,
        )
        for o in original.observations
    }
    after = {
        o.source_id: (
            o.text,
            tuple(asdict(loc) for loc in o.locations),
            o.extraction.raw_candidate_id,
        )
        for o in result.observations
    }
    assert before == after


def test_blank_and_corrupt(tmp_path):
    from fixtures.phase1 import documents
    from idp.pdf.native.preflight import PdfAdmissionError

    blank = tmp_path / "blank.pdf"
    blank.write_bytes(documents()["blank"])
    canonical = DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
        blank, tmp_path / "blank-out"
    )
    assert canonical["pages"][0]["classification"] == "blank"
    assert canonical["pages"][0]["blocks"] == []
    with pytest.raises(PdfAdmissionError):
        DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
            FIX / "broken.pdf", tmp_path / "bad"
        )
    assert not (tmp_path / "bad/canonical.json").exists()
    assert (
        json.loads((tmp_path / "bad/unified_error.json").read_text())["status"]
        == "failed"
    )


def test_missing_tesseract(tmp_path):
    from idp.ocr.backends.tesseract import BackendUnavailable, TesseractBackend

    with pytest.raises(BackendUnavailable):
        TesseractBackend(tmp_path, executable="definitely-no-such-tesseract")


def test_tsv_confidence_and_geometry():
    from idp.ocr.backends.tesseract import parse_tsv

    raw = b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t20\t30\t40\t10\t87.5\tHello\n"
    block = parse_tsv(raw, (100, 100))[0]
    assert block.text == "Hello" and block.confidence == 0.875
    assert block.bbox_px == (20, 30, 60, 40)
    assert block.payload["words"][0]["bbox_px"] == (20, 30, 60, 40)
    with pytest.raises(ValueError):
        parse_tsv(raw, (10, 10))
    assert parse_tsv(raw.split(b"\n")[0] + b"\n", (100, 100)) == ()


@REAL_OCR
def test_real_region_acquisition(tmp_path):
    from idp.ocr.backends.tesseract import TesseractBackend, TesseractConfig
    from idp.pdf.acquire import AcquisitionRequest, BackendAcquirer
    from idp.pdf.geometry import Affine
    from idp.pdf.merge import EvidenceMerger
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page, transform_image
    from idp.pdf.resource import ResourceLedger

    backend = TesseractBackend(tmp_path, TesseractConfig("eng", 6))
    with PdfSource((FIX / "native.pdf").read_bytes()) as source:
        native = PdfParsingEngine().extract_native(source.data, source=source)
        target = native.observations[1]
        b = target.locations[0].bbox
        data, frame = render_page(source, 1, dpi=216)
        x0, y0, x1, y1 = frame.from_pdf_pt((b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2))
        left, top = int(x0), int(y0)
        data, frame = transform_image(
            data,
            frame,
            kind="crop",
            matrix=Affine(e=-left, f=-top),
            output_size=(int(x1) - left, int(y1) - top),
        )
        executor = BackendAcquirer(
            lambda s, p, plan, deadline: backend.read(
                data,
                s,
                p,
                plan,
                deadline=deadline,
                target_region_id=target.extraction.region.id,
            ),
            ResourceLedger(monotonic() + 30),
        )
        result = executor.acquire_regions(
            source,
            1,
            AcquisitionRequest(
                "region-test", frame, ((0, 0, *frame.steps[-1].output_size),)
            ),
            deadline=monotonic() + 20,
        )
        assert "Independent expected text" in " ".join(b.text for b in result.blocks)
        prepared = EvidenceMerger().merge(native, (result,))
        updated = next(
            o for o in prepared.observations if o.source_id == target.source_id
        )
        assert updated.text == target.text
        assert updated.extraction.raw_candidate_id == target.extraction.raw_candidate_id
        assert len(updated.extraction.candidates) > len(target.extraction.candidates)


def test_shadow_failure_preserves_legacy(tmp_path, monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError("controlled unified failure")

    monkeypatch.setattr(DeepDocService, "_unified", failure)
    service = DeepDocService(DeepDocConfig(engine="shadow", language="eng"))
    result = service.process_pdf(FIX / "native.pdf", tmp_path)
    assert result == json.loads((tmp_path / "canonical.json").read_text())
    assert (
        json.loads((tmp_path / "shadow_diff.json").read_text())["status"]
        == "unified_failed"
    )


@REAL_OCR
@pytest.mark.integration
def test_real_shadow_scan(tmp_path):
    cfg = DeepDocConfig(engine="shadow", legacy_lane="fast", language="eng")
    result = DeepDocService(cfg).process_pdf(FIX / "scan.pdf", tmp_path)
    authoritative = (tmp_path / "canonical.json").read_bytes()
    comparison = json.loads((tmp_path / "shadow_diff.json").read_text())
    assert comparison["status"] == "compared"
    assert comparison["unified_report"]["ocr_invocations"] == 1
    assert result["pipeline_version"] != "deepdoc-unified:3"
    assert (tmp_path / "canonical.json").read_bytes() == authoritative
    assert list((tmp_path / "shadow").glob("*/canonical.json"))


@REAL_OCR
@pytest.mark.integration
def test_real_vietnamese_pdf(tmp_path):
    font = next(
        p
        for p in (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        if p.is_file()
    )
    expected = "Tiếng Việt: phương trình và hình học"
    with fitz.open() as text:
        page = text.new_page(width=480, height=240)
        page.insert_font(fontname="unicode", fontfile=str(font))
        page.insert_text((30, 80), expected, fontname="unicode", fontsize=18)
        image = page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
        with fitz.open() as scan:
            scan.new_page(width=480, height=240).insert_image(
                fitz.Rect(0, 0, 480, 240), stream=image
            )
            path = tmp_path / "vietnamese-scan.pdf"
            scan.save(path)
    canonical = DeepDocService(
        DeepDocConfig(engine="unified", language="vie+eng")
    ).process_pdf(path, tmp_path / "out")
    text = " ".join(b["text"] for p in canonical["pages"] for b in p["blocks"])
    assert "phương trình" in text and "hình học" in text
    assert (
        json.loads((tmp_path / "out/run_report.json").read_text())["ocr_invocations"]
        == 1
    )


@REAL_OCR
@pytest.mark.parametrize("failure", ["timeout", "nonzero"])
def test_actual_subprocess_failure_cleanup(tmp_path, monkeypatch, failure):
    import idp.ocr.backends.tesseract as module
    from idp.pdf.acquire import AcquisitionRequest, BackendAcquirer
    from idp.pdf.native import preflight
    from idp.pdf.render import render_page
    from idp.pdf.resource import ResourceLedger

    processes, staged = [], []
    backend = module.TesseractBackend(
        tmp_path, module.TesseractConfig("eng", timeout_seconds=0.1)
    )
    original_run, original_popen = module.run_bounded_process, subprocess.Popen

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    def controlled(command, **kwargs):
        staged.append(Path(command[1]).parent)
        code = (
            "import time; time.sleep(20)"
            if failure == "timeout"
            else "raise SystemExit(4)"
        )
        return original_run([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(preflight.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "run_bounded_process", controlled)
    with preflight.PdfSource((FIX / "scan.pdf").read_bytes()) as source:
        data, frame = render_page(source, 1)
        ledger = ResourceLedger(monotonic() + 5)
        acquirer = BackendAcquirer(
            lambda s, p, plan, deadline: backend.read(
                data, s, p, plan, deadline=deadline
            ),
            ledger,
        )
        with pytest.raises(module.OCRTimeout if failure == "timeout" else RuntimeError):
            acquirer.acquire_page(
                source,
                1,
                AcquisitionRequest("failure-test", frame),
                deadline=monotonic() + 5,
            )
        assert ledger.calls == 1 and ledger._items["failure-test"] == "failed"
    assert processes and all(p.poll() is not None for p in processes)
    assert all(p.stdout.closed and p.stderr.closed for p in processes)
    assert all(not p.exists() for p in staged)


@REAL_OCR
def test_missing_traineddata(tmp_path):
    from idp.ocr.backends.tesseract import (
        BackendUnavailable,
        TesseractBackend,
        TesseractConfig,
    )

    with pytest.raises(BackendUnavailable, match="traineddata"):
        TesseractBackend(tmp_path, TesseractConfig("no_such_traineddata"))


def test_hidden_text_signal():
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource

    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        page.insert_text((30, 80), "Untrusted hidden OCR layer text", render_mode=3)
        data = doc.tobytes()
    with PdfSource(data) as source:
        native = PdfParsingEngine().extract_native(data, source=source)
        signals = profile_pages(native, source=source)
        assert signals[0].hidden_layer_suspect is True
        assert (
            PdfRouter().route(native.admission.source_sha256, signals).pages[0].route
            == PageRoute.OCR_PAGE
        )


@pytest.mark.parametrize(
    "name", ["native.pdf", "columns.pdf", "table.pdf", "formula.pdf", "mixed.pdf"]
)
def test_layout_v2_preserves_native_records(name):
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.layout import PdfLayoutPolicy

    engine = PdfParsingEngine()
    data = (FIX / name).read_bytes()
    native = engine.extract_native(data)
    old = engine.finalize(native)
    new = engine.finalize(native, layout_policy=PdfLayoutPolicy(version="pdf-layout:2"))
    fields = lambda r: {
        o.source_id: (o.text, o.locations, o.extraction) for o in r.observations
    }
    assert fields(old) == fields(new)
    assert len(new.observations) == len({o.source_id for o in new.observations})


@REAL_OCR
def test_embedded_image_selective_routing(tmp_path):
    from fixtures.phase1 import documents

    source = tmp_path / "mixed4.pdf"
    source.write_bytes(documents()["mixed4"])
    result = DeepDocService(
        DeepDocConfig(engine="unified", language="eng")
    ).process_pdf(source, tmp_path / "out")
    routes = json.loads((tmp_path / "out/routes.json").read_text())["pages"]
    assert [p["route"] for p in routes] == [
        "native_only",
        "ocr_page",
        "native_plus_region_ocr",
        "blank",
    ]
    assert routes[2]["regions"]
    assert result["pages"][0]["blocks"]


@pytest.mark.parametrize(
    "confidence,eligible",
    [
        (0.0, False),
        (0.59, False),
        (0.60, False),
        (0.79, False),
        (0.8, True),
        (0.99, True),
    ],
)
def test_publication_confidence_filters_content(
    tmp_path, monkeypatch, confidence, eligible
):
    from idp.evidence.contracts import DeepDocProducer
    from idp.pdf.acquire import AcquisitionResult, OcrBlock
    from idp.pdf.merge import EvidenceMerger
    from idp.pdf.native import engine as module
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.native.quality import PdfQualityPolicy
    from idp.pdf.projector import project_v1
    from idp.pdf.publication import assess_publication
    from idp.pdf.render import render_page

    monkeypatch.setattr(module, "extract_pdf_figures", lambda *a, **k: ((), ()))
    engine = PdfParsingEngine()
    with PdfSource((FIX / "scan.pdf").read_bytes()) as source:
        native = engine.extract_native(source.data, source=source)
        _, frame = render_page(source, 1)
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test-ocr", "1"),
            "test",
            "0" * 64,
            "fixture:raw",
            "1" * 64,
            (
                OcrBlock(
                    "line", "Controlled publication text", (20, 20, 200, 40), confidence
                ),
            ),
        )
        prepared = EvidenceMerger().merge(native, (result,))
        record = engine.finalize(
            native,
            source=source,
            prepared=prepared,
            quality_policy=PdfQualityPolicy(version="pdf-quality-gate:2"),
        )
        plan = PdfRouter().route(native.admission.source_sha256, profile_pages(native))
        decisions = assess_publication(record, plan)
        assert decisions[0].eligible is eligible
        assert decisions[0].status == "OCR_TRANSCRIPTION_UNVERIFIED"
        canonical = project_v1(record, native, plan, decisions, FIX / "scan.pdf")
        assert bool(canonical["pages"][0]["blocks"]) is eligible
        assert record.observations[0].text == "Controlled publication text"


@REAL_OCR
def test_retry_exhaustion_is_bounded(tmp_path):
    cfg = DeepDocConfig(engine="unified", language="eng", retry_limit=1)
    DeepDocService(cfg).process_pdf(FIX / "scan.pdf", tmp_path)
    attempts = json.loads((tmp_path / "ocr_attempts.json").read_text())
    # Existing low-resolution scan contains a measured line below .8; retry is
    # quality-triggered and both source-backed attempts remain available.
    assert 1 <= len(attempts) <= 2
    assert len({a["id"] for a in attempts}) == len(attempts)
    assert all(a["status"] == "success" for a in attempts)
    if len(attempts) == 2:
        assert attempts[0]["render_id"] != attempts[1]["render_id"]


@pytest.mark.parametrize(
    "spanning,rows", [(True, 2), (True, 4), (False, 2), (False, 4)]
)
def test_table_barriers_multirow_and_column(spanning, rows):
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.layout import PdfLayoutPolicy

    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        for n in range(4):
            page.insert_text((40, 70 + n * 20), f"Left introduction {n}")
            page.insert_text((340, 70 + n * 20), f"Right introduction {n}")
        right = 560 if spanning else 280
        middle = (40 + right) / 2
        for n in range(rows + 1):
            page.draw_line((40, 200 + n * 30), (right, 200 + n * 30))
        for x in (40, middle, right):
            page.draw_line((x, 200), (x, 200 + rows * 30))
        for n in range(rows):
            page.insert_text((50, 220 + n * 30), f"Cell {n}")
            page.insert_text((middle + 10, 220 + n * 30), f"Grade{n}")
        page.insert_text((40, 400), "AFTERLEFT")
        page.insert_text((340, 400), "AFTERRIGHT")
        data = doc.tobytes()
    engine = PdfParsingEngine()
    native = engine.extract_native(data)
    record = engine.finalize(
        native, layout_policy=PdfLayoutPolicy(version="pdf-layout:2")
    )
    text = "\n".join(o.text or "" for o in record.observations)
    for n in range(rows):
        assert text.index(f"Grade{n}") < text.index("AFTERLEFT")
    assert len(record.observations) == len(native.observations) + len(native.figures)


def test_render_budget_stops_before_render(tmp_path, monkeypatch):
    import idp.pdf.service as module
    from fixtures.phase1 import documents
    from idp.pdf.resource import BudgetExceeded

    path = tmp_path / "blank.pdf"
    path.write_bytes(documents()["blank"])
    monkeypatch.setattr(
        module,
        "render_page",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not render")),
    )
    with pytest.raises(BudgetExceeded):
        # "absolute" keeps the configured job budget as is; the default
        # per-page mode would scale it to the document (audit IDP-002).
        DeepDocService(
            DeepDocConfig(engine="unified", max_total_pixels=1, budget_mode="absolute")
        ).process_pdf(path, tmp_path / "out")


@REAL_OCR
def test_same_pixels_legacy_tesseract_accuracy(tmp_path):
    from idp.evidence.serde import load
    from idp.ocr.fast import run_fast
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_for_ocr

    source = FIX / "scan.pdf"
    with PdfSource(source.read_bytes()) as opened:
        # Exactly the pixels the unified service sends to OCR.
        image, frame = render_for_ocr(opened, 1, dpi=216, max_pixels=4_000_000)
        path = tmp_path / "same-pixels.png"
        path.write_bytes(image)
        prepared = {
            1: {
                "image": str(path),
                "source_sha256": opened.report.source_sha256,
                "image_sha256": hashlib.sha256(image).hexdigest(),
            }
        }
    run_fast(
        source,
        [1],
        tmp_path / "legacy",
        dpi=216,
        lang="eng",
        psm=3,
        region_recovery=False,
        prepared_pages=prepared,
    )
    DeepDocService(DeepDocConfig(engine="unified", language="eng")).process_pdf(
        source, tmp_path / "unified"
    )
    legacy = json.loads((tmp_path / "legacy/canonical.json").read_text())
    record = load((tmp_path / "unified/extraction.json").read_text())
    a = " ".join(b["text"] for p in legacy["pages"] for b in p["blocks"])
    b = " ".join(
        o.text or "" for o in record.observations if o.extraction_source.value == "OCR"
    )
    assert a.split() == b.split()
    # Independent ground truth comes from the fixture generator, not legacy OCR.
    ground_truth = "Phase zero document. Native source evidence for regression. Independent expected text. Page number 1."

    def distance(x, y):
        previous = list(range(len(y) + 1))
        for i, item in enumerate(x, 1):
            current = [i]
            for j, other in enumerate(y, 1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[j] + 1,
                        previous[j - 1] + (item != other),
                    )
                )
            previous = current
        return previous[-1]

    metrics = {
        "schema": "deepdoc-controlled-benchmark:1",
        "same_image_sha256": frame.steps[-1].output_sha256,
        "ocr_cer_legacy": distance(ground_truth, a) / len(ground_truth),
        "ocr_cer_unified": distance(ground_truth, b) / len(ground_truth),
        "ocr_wer_legacy": distance(ground_truth.split(), a.split())
        / len(ground_truth.split()),
        "ocr_wer_unified": distance(ground_truth.split(), b.split())
        / len(ground_truth.split()),
        "ground_truth_source": "tests/fixtures/generate.py",
        "peak_memory": "NOT MEASURED",
    }
    assert metrics["ocr_cer_unified"] == metrics["ocr_cer_legacy"]
    assert metrics["ocr_cer_unified"] == 0
    (tmp_path / "benchmark.json").write_text(json.dumps(metrics, indent=2))


def test_service_default_legacy_and_cli(tmp_path, monkeypatch):
    import os

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy default must not execute unified")

    monkeypatch.setattr(DeepDocService, "_unified", forbidden)
    canonical = DeepDocService().process_pdf(FIX / "native.pdf", tmp_path / "legacy")
    assert canonical["pipeline_version"] != "deepdoc-unified:3"
    assert not (tmp_path / "legacy/routes.json").exists()
    service_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "idp.pdf.service",
            str(FIX / "native.pdf"),
            "--out",
            str(tmp_path / "cli"),
            "--engine",
            "unified",
        ],
        cwd=service_root,
        env={**os.environ, "PYTHONPATH": str(service_root)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (
        json.loads((tmp_path / "cli/canonical.json").read_text())["pipeline_version"]
        == "deepdoc-unified:3"
    )


def test_unified_layout_and_reconcile_once(tmp_path, monkeypatch):
    from idp.pdf.native import engine as module

    calls = {}
    for name in ("apply_pdf_layout", "reconcile_pages"):
        original = getattr(module, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            calls[_name] = calls.get(_name, 0) + 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)
    DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
        FIX / "native.pdf", tmp_path
    )
    assert calls == {"apply_pdf_layout": 1, "reconcile_pages": 1}


def test_explicit_reread_wrong_geometry_rejected():
    from idp.evidence.contracts import DeepDocProducer
    from idp.pdf.acquire import AcquisitionResult, OcrBlock
    from idp.pdf.merge import ContractViolation, EvidenceMerger
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    with PdfSource((FIX / "native.pdf").read_bytes()) as source:
        native = PdfParsingEngine().extract_native(source.data, source=source)
        _, frame = render_page(source, 1)
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test", "1"),
            "test",
            "0" * 64,
            "fixture:raw",
            "1" * 64,
            (
                OcrBlock(
                    "wrong",
                    "Not this region",
                    (0, 800, 100, 840),
                    0.99,
                    target_region_id=native.observations[0].extraction.region.id,
                ),
            ),
        )
        with pytest.raises(ContractViolation):
            EvidenceMerger().merge(native, (result,))


@REAL_OCR
def test_suspect_native_region_real_service(tmp_path):
    import re

    from idp.evidence.serde import load

    font = next(
        p
        for p in (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        if p.is_file()
    )
    path = tmp_path / "suspect.pdf"
    text = "Native evidence for a suspect glyph X"
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=300)
        font_xref = page.insert_font(fontname="unicode", fontfile=str(font))
        page.insert_text(
            (30, 90),
            text,
            fontname="unicode",
            fontsize=18,
        )
        # Arial on Windows has no replacement glyph. Keep the ink readable
        # and corrupt the ToUnicode mapping of the visible X instead.
        glyphs = fitz.Font(fontfile=str(font))
        chars = sorted(set(text))
        mapping = "\n".join(
            f"<{glyphs.has_glyph(ord(char)):04X}> <{0xE001 if char == 'X' else ord(char):04X}>"
            for char in chars
        )
        cmap_xref = int(doc.xref_get_key(font_xref, "ToUnicode")[1].split()[0])
        cmap = re.sub(rb"\d+\s+beginbf(range|char).*?endbf\1\s*", b"", doc.xref_stream(cmap_xref), flags=re.S)
        replacement = f"{len(chars)} beginbfchar\n{mapping}\nendbfchar\nendcmap".encode()
        doc.update_stream(cmap_xref, cmap.replace(b"endcmap", replacement))
        doc.save(path)
    DeepDocService(DeepDocConfig(engine="unified", language="eng", psm=6)).process_pdf(
        path, tmp_path / "out"
    )
    routes = json.loads((tmp_path / "out/routes.json").read_text())
    assert routes["pages"][0]["route"] == "native_plus_region_ocr"
    attempts = json.loads((tmp_path / "out/ocr_attempts.json").read_text())
    assert attempts and attempts[0]["region"] == 0 and attempts[0]["lines"] > 0
    record = load((tmp_path / "out/extraction.json").read_text(encoding="utf-8"))
    assert any(len(o.extraction.candidates) > 1 for o in record.observations)
    for obs in record.observations:
        assert obs.extraction_source.value != "OCR"  # reread, not replacement source
        source = next(
            c
            for c in obs.extraction.candidates
            if c.id == obs.extraction.source_candidate_id
        )
        assert obs.text == source.text


@REAL_OCR
def test_real_ocr_cropbox_rotate(tmp_path):
    from idp.evidence.serde import load

    path = tmp_path / "rotated.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        page.insert_text(
            (100, 480), "Rotated source evidence for geometry", fontsize=16, rotate=90
        )
        page.set_cropbox(fitz.Rect(20, 20, 380, 580))
        page.set_rotation(90)
        doc.save(path)
    DeepDocService(
        DeepDocConfig(engine="unified", language="eng", force_ocr=True)
    ).process_pdf(path, tmp_path / "out")
    record = load((tmp_path / "out/extraction.json").read_text())
    proposals = record.attributes["ocr_proposals"]
    result = load(proposals[0]["record_json"])
    assert result.frame.geometry[:2] == (560, 360)
    assert result.frame.geometry[3] == 90
    assert "Rotated source evidence" in " ".join(b.text for b in result.blocks)
    for block in result.blocks:
        x0, y0, x1, y1 = result.frame.to_pdf_pt(block.bbox_px)
        assert 0 <= x0 < x1 <= 560 and 0 <= y0 < y1 <= 360
