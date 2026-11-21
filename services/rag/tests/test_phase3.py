"""Phase 3: real PDF, real OCR, publication and shadow isolation."""

import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

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

    monkeypatch.setattr(DeepDocService, "_default_registry", forbidden)
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


def test_overlapping_table_regions_expand_to_source_observations():
    from dataclasses import dataclass
    from types import SimpleNamespace as Object

    from idp.evidence.contracts import DeepDocBoundingBox, DeepDocSourceLocation
    from idp.pdf.native.layout import PdfLayoutPolicy, order_observations

    def location(x0, y0, x1, y1):
        return DeepDocSourceLocation(1, 600, 800, DeepDocBoundingBox(x0, y0, x1, y1))

    def table(key, box):
        candidate = Object(id=key, table=True)
        region = Object(id=key, locations=(box,))
        return Object(
            trace=Object(
                region=region, candidates=(candidate,), source_candidate_id=key
            )
        )

    @dataclass
    class Observation:
        source_id: str
        order: int
        locations: tuple
        type_hint: str | None = None
        source_order: int | None = None
        kind = Object(value="TEXT")

    observations = [
        Observation(
            source_id=key,
            order=index,
            locations=(location(60, y, 120, y + 10),),
        )
        for index, (key, y) in enumerate(
            (("header", 200), ("cell", 220), ("next", 280))
        )
    ]
    ordered, *_ = order_observations(
        observations,
        policy=PdfLayoutPolicy(version="pdf-layout:3"),
        structures=(
            table("table:inner", location(50, 190, 130, 240)),
            table("table:outer", location(40, 180, 140, 250)),
        ),
    )
    assert [item.source_id for item in ordered] == ["header", "cell", "next"]


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


def test_embedded_image_selective_routing(tmp_path, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    from fixtures.phase1 import documents

    source = tmp_path / "mixed4.pdf"
    source.write_bytes(documents()["mixed4"])
    result = DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
        source, tmp_path / "out"
    )
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


def test_retry_exhaustion_is_bounded(tmp_path, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    cfg = DeepDocConfig(engine="unified", retry_limit=1)
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
