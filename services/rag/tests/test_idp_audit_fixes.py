"""Regression tests for the IDP full audit (findings IDP-001 .. IDP-017).

Each test names the finding it pins down. OCR is a deterministic stand-in
unless a test says otherwise, so the real render -> acquisition -> merge ->
publication -> projection path runs without Tesseract.
"""

import hashlib
import json
import os
from pathlib import Path

import fitz
import pytest
from idp_test_backends import use_ocr_backend
from idp.evidence.contracts import DeepDocProducer
from idp.ocr.backends.errors import BackendUnavailable, OCRTimeout
from idp.pdf.acquire import AcquisitionResult, OcrBlock
from idp.pdf.publication import PublicationPolicy
from idp.pdf.resource import BudgetExceeded
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import iter_retrievable_blocks, to_v1

FIX = Path(__file__).parent / "fixtures/generated"


class FixedOCR:
    """One confident OCR line per page/crop; optional failure on pages."""

    config_sha256 = "f" * 64
    fail_pages = ()
    calls = 0

    def __init__(self, out=None, config=None):
        self.languages = frozenset({"vie", "eng"})

    def read(self, image, source, page, plan, *, deadline, target_region_id=None):
        type(self).calls += 1
        if page in self.fail_pages:
            raise OCRTimeout("simulated page OCR timeout")
        frame = plan.frame
        w, h = frame.steps[-1].output_size
        block = OcrBlock(
            f"p{page}",
            f"Recognized scan text on page {page}",
            (1, 1, max(2, w // 2), max(2, h // 8)),
            0.95,
            target_region_id=target_region_id,
        )
        return AcquisitionResult(
            frame,
            DeepDocProducer("fixed-ocr", "1"),
            "fixed-family",
            self.config_sha256,
            "fixed:raw",
            hashlib.sha256(image).hexdigest(),
            (block,),
        )


@pytest.fixture
def fixed_ocr(monkeypatch):
    class Backend(FixedOCR):
        calls = 0

    use_ocr_backend(monkeypatch, Backend)
    return Backend


def run(path, out, **config):
    return DeepDocService(DeepDocConfig(engine="unified", **config)).process_pdf(
        path, out
    )


def report(out):
    return json.loads((Path(out) / "run_report.json").read_text(encoding="utf-8"))


def v1_blocks(doc):
    if doc["schema_version"] == "idp-canonical-2":
        doc = to_v1(doc)
    return [b for p in doc["pages"] for b in p["blocks"]]


# A Unicode font with Vietnamese glyphs (the base-14 fonts have none).
FONT = next(
    (
        p
        for p in (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        if p.is_file()
    ),
    None,
)


def native_pdf(path, pages=3):
    if FONT is None:
        pytest.skip("Unicode TrueType font required")
    with fitz.open() as pdf:
        for n in range(pages):
            page = pdf.new_page(width=595, height=842)
            page.insert_font(fontname="unicode", fontfile=str(FONT))
            # Multi-line native blocks: each block's text contains newlines.
            page.insert_textbox(
                fitz.Rect(72, 90, 520, 400),
                f"Chương {n + 1}: Hàm số liên tục.\n"
                "Cho hàm số f xác định trên khoảng K.\n"
                "Hàm số f liên tục tại x0 nếu giới hạn tồn tại.",
                fontname="unicode",
                fontsize=12,
            )
        pdf.save(path)
    return path


def scan_pdf(path, pages):
    with fitz.open() as src:
        page = src.new_page(width=595, height=842)
        page.insert_text((72, 100), "A scanned paragraph of course text.", fontsize=14)
        png = page.get_pixmap(dpi=100).tobytes("png")
    with fitz.open() as pdf:
        for _ in range(pages):
            pdf.new_page(width=595, height=842).insert_image(
                fitz.Rect(0, 0, 595, 842), stream=png
            )
        pdf.save(path)
    return path


# IDP-001 -------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,suspect",
    [
        ("a\nb", 0),
        ("a\r\n\tb\x0cc", 0),
        ("a b", 0),
        ("a\x00b", 1),
        ("a\x1cb", 1),
        ("a�b", 1),
        ("ab", 1),
    ],
)
def test_text_health_ignores_layout_whitespace_only(text, suspect):
    from idp.pdf.profiling import text_health

    assert text_health(text)[1] == suspect


def test_clean_multiline_native_pdf_needs_no_ocr(tmp_path, fixed_ocr):
    path = native_pdf(tmp_path / "native.pdf", pages=3)
    doc = run(path, tmp_path / "out")
    routes = json.loads((tmp_path / "out/routes.json").read_text())
    assert {p["route"] for p in routes["pages"]} == {"native_only"}
    assert fixed_ocr.calls == 0
    run_report = report(tmp_path / "out")
    assert run_report["ocr_invocations"] == 0 and run_report["render_pixels"] == 0
    assert any("liên tục" in b["text"] for b in v1_blocks(doc))


def test_long_native_pdf_is_fast_and_complete(tmp_path, fixed_ocr):
    path = native_pdf(tmp_path / "long.pdf", pages=60)
    run(path, tmp_path / "out")
    run_report = report(tmp_path / "out")
    assert run_report["ocr_invocations"] == 0
    assert run_report["status"] == "SUCCESS"
    assert run_report["published_blocks"] >= 60
    assert run_report["seconds"] < 30


# IDP-002 -------------------------------------------------------------------


@pytest.mark.unit
def test_effective_budget_scales_with_pages_and_is_capped():
    cfg = DeepDocConfig(engine="unified")
    small = cfg.effective_limits(1)
    assert small == {
        "max_total_pixels": cfg.max_total_pixels,
        "max_calls": cfg.max_calls,
        "max_regions": cfg.max_regions,
    }
    book = cfg.effective_limits(300)
    # Region budget scales too (a fixed 100 crashed books past region 100).
    assert book["max_regions"] == 300 * cfg.max_regions
    assert book["max_total_pixels"] >= 300 * cfg.max_pixels * 2
    assert book["max_calls"] >= 300 * cfg.max_calls_per_page
    huge = cfg.effective_limits(10**6)
    assert huge == {
        "max_total_pixels": cfg.max_total_pixels_cap,
        "max_calls": cfg.max_calls_cap,
        "max_regions": 100_000,
    }
    absolute = DeepDocConfig(engine="unified", budget_mode="absolute")
    assert absolute.effective_limits(300)["max_total_pixels"] == 100_000_000


def test_thirty_page_scan_fits_default_budget(tmp_path, fixed_ocr):
    path = scan_pdf(tmp_path / "scan.pdf", pages=30)
    with pytest.raises(BudgetExceeded):
        run(path, tmp_path / "absolute", budget_mode="absolute", ocr_workers=1)
    doc = run(path, tmp_path / "out", ocr_workers=1)
    run_report = report(tmp_path / "out")
    assert run_report["budget"]["mode"] == "per_page"
    assert run_report["budget"]["pages_in_scope"] == 30
    assert run_report["render_pixels"] > 100_000_000
    assert len(run_report["ocr_pages"]) == 30
    assert sum(bool(p["blocks"]) for p in doc["pages"]) == 30


# IDP-003 / IDP-008 ---------------------------------------------------------


def test_one_failed_ocr_page_does_not_fail_the_job(tmp_path, fixed_ocr):
    fixed_ocr.fail_pages = (2,)
    path = scan_pdf(tmp_path / "scan.pdf", pages=3)
    doc = run(path, tmp_path / "out", ocr_workers=1)
    pages = {p["page_id"]: p for p in doc["pages"]}
    assert pages[1]["blocks"] and pages[3]["blocks"] and not pages[2]["blocks"]
    assert [f["code"] for f in pages[2]["review"]] == ["OCR_FAILED"]
    written = json.loads((tmp_path / "out/report.json").read_text())
    assert written["failed_pages"] == [
        {"page": 2, "error": "OCRTimeout", "stage": "ocr"}
    ]
    assert written["status"] == "REVIEW"
    assert "FAILED_PAGES" in written["status_reasons"]
    routes = json.loads((tmp_path / "out/routes.json").read_text())
    assert routes["pages"][1]["route"] == "review"
    assert routes["pages"][1]["reasons"][-1] == "OCR_FAILED:OCRTimeout"


def test_page_isolation_can_be_disabled(tmp_path, fixed_ocr):
    fixed_ocr.fail_pages = (2,)
    path = scan_pdf(tmp_path / "scan.pdf", pages=3)
    with pytest.raises(OCRTimeout):
        run(path, tmp_path / "out", ocr_workers=1, page_isolation=False)


def test_job_budget_failure_still_fails_the_job(tmp_path, fixed_ocr):
    path = scan_pdf(tmp_path / "scan.pdf", pages=3)
    with pytest.raises(BudgetExceeded):
        run(path, tmp_path / "out", budget_mode="absolute", max_calls=1)


def test_failed_scan_page_canonical_v2_validates(tmp_path, fixed_ocr):
    from idp.publish import load_canonical

    fixed_ocr.fail_pages = (1,)
    path = scan_pdf(tmp_path / "scan.pdf", pages=2)
    doc = run(path, tmp_path / "out", canonical_version=2, ocr_workers=1)
    loaded = load_canonical(tmp_path / "out/canonical.json")
    assert loaded["pages"][0]["status"] == "review"
    assert {b["page"] for b in iter_retrievable_blocks(doc)} == {2}


def test_clean_native_run_reports_success_with_real_metrics(tmp_path, fixed_ocr):
    path = native_pdf(tmp_path / "native.pdf", pages=2)
    run(path, tmp_path / "out")
    written = json.loads((tmp_path / "out/report.json").read_text())
    assert written["status"] == "SUCCESS" and written["failed_pages"] == []
    assert written["publication"]["withheld_chars_ratio"] == 0
    assert written["publication"]["published_chars"] > 0


# IDP-004 -------------------------------------------------------------------


def scan_with_layer(path, visible, hidden):
    with fitz.open() as src:
        page = src.new_page(width=595, height=842)
        for i, text in enumerate(visible):
            page.insert_text((72, 100 + i * 24), text, fontsize=14)
        png = page.get_pixmap(dpi=100).tobytes("png")
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=png)
        for i, text in enumerate(hidden):
            page.insert_text((72, 100 + i * 24), text, fontsize=14, render_mode=3)
        pdf.save(path)
    return path


@pytest.mark.parametrize("version", [1, 2])
def test_wrong_hidden_layer_is_replaced_by_confident_ocr(tmp_path, monkeypatch, version):
    """A layer that lost its diacritics must not hide the page's content."""
    visible = ["Ham so lien tuc tren khoang K", "Gioi han cua ham so tai x0"]
    truth = ["Hàm số liên tục trên khoảng K", "Giới hạn của hàm số tại x0"]
    fixes = dict(zip(visible, truth))

    class ReadsVisiblePage(FixedOCR):
        def read(self, image, source, page, plan, *, deadline, target_region_id=None):
            frame = plan.frame
            w, h = frame.steps[-1].output_size
            blocks = []
            with fitz.open(stream=source.data, filetype="pdf") as doc:
                lines = [
                    line
                    for b in doc[page - 1].get_text("dict")["blocks"]
                    for line in b.get("lines", ())
                ]
            for i, line in enumerate(lines):
                text = "".join(s["text"] for s in line["spans"]).strip()
                x0, y0, x1, y1 = frame.from_pdf_pt(tuple(line["bbox"]))
                box = (max(0, x0), max(0, y0), min(w, x1), min(h, y1))
                blocks.append(OcrBlock(f"l{i}", fixes.get(text, text), box, 0.92))
            return AcquisitionResult(
                frame,
                DeepDocProducer("fixed-ocr", "1"),
                "fixed-family",
                self.config_sha256,
                "fixed:raw",
                hashlib.sha256(image).hexdigest(),
                tuple(blocks),
            )

    use_ocr_backend(monkeypatch, ReadsVisiblePage)
    path = scan_with_layer(tmp_path / "scan.pdf", truth, visible)
    doc = run(path, tmp_path / "out", canonical_version=version)
    texts = [b["text"] for b in v1_blocks(doc)]
    assert texts == truth
    assert report(tmp_path / "out")["status"] == "SUCCESS"


# IDP-005 -------------------------------------------------------------------


def skewed_publication(policy):
    from idp.pdf.merge import EvidenceMerger
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.native.quality import PdfQualityPolicy
    from idp.pdf.profiling import profile_pages
    from idp.pdf.publication import assess_publication
    from idp.pdf.render import render_page
    from idp.pdf.router import PdfRouter

    with PdfSource((FIX / "scan.pdf").read_bytes()) as source:
        engine = PdfParsingEngine()
        native = engine.extract_native(source.data, source=source)
        _, frame = render_page(source, 1)
        # Neighbouring paragraphs of a skewed scan: their axis-aligned boxes
        # overlap (coverage 0.33, IoU 0.2) while reading different words.
        blocks = (
            OcrBlock("one", "alpha beta gamma delta epsilon", (20, 20, 400, 80), 0.95),
            OcrBlock("two", "zeta eta theta iota kappa", (20, 60, 400, 120), 0.95),
            # Same area, different reading: still a conflicting duplicate.
            OcrBlock("three", "lambda mu nu xi omicron", (20, 60, 400, 120), 0.95),
        )
        result = AcquisitionResult(
            frame,
            DeepDocProducer("controlled-unit-ocr", "1"),
            "unit",
            "0" * 64,
            "unit:raw",
            "1" * 64,
            blocks,
        )
        prepared = EvidenceMerger().merge(native, (result,))
        record = engine.finalize(
            native,
            prepared=prepared,
            quality_policy=PdfQualityPolicy(version="pdf-quality-gate:2"),
        )
        plan = PdfRouter().route(native.admission.source_sha256, profile_pages(native))
        decisions = assess_publication(record, plan, policy)
        texts = {o.source_id: o.text for o in record.observations}
        return {texts[d.source_id]: d for d in decisions}


@pytest.mark.unit
def test_skewed_ocr_paragraphs_are_not_duplicates():
    current = skewed_publication(PublicationPolicy())
    assert current["alpha beta gamma delta epsilon"].eligible
    assert current["zeta eta theta iota kappa"].eligible
    assert current["lambda mu nu xi omicron"].reasons == ("DUPLICATE_REGION_REVIEW",)



@pytest.mark.unit
def test_ocr_duplicate_rule():
    from idp.pdf.publication import ocr_duplicate

    a, b = (0, 0, 100, 60), (0, 40, 100, 100)
    assert not ocr_duplicate(a, "one two three four", b, "five six seven eight")
    assert ocr_duplicate(a, "one two three four", b, "one two three four")
    assert ocr_duplicate(a, "one two", a, "completely different")


# IDP-006 -------------------------------------------------------------------


def native_with_logo(path):
    with fitz.open() as src:
        logo = src.new_page(width=200, height=100)
        logo.insert_text((20, 60), "LOGO", fontsize=30)
        png = logo.get_pixmap(dpi=72).tobytes("png")
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(400, 40, 560, 120), stream=png)
        page.insert_textbox(
            fitz.Rect(72, 200, 520, 500),
            "Native course text stays publishable.\nA second native line.",
            fontname="helv",
            fontsize=12,
        )
        pdf.save(path)
    return path


@pytest.mark.parametrize("version", [1, 2])
def test_missing_ocr_keeps_native_text_outside_unread_regions(
    tmp_path, monkeypatch, version
):
    class Missing:
        def __init__(self, *a, **k):
            raise BackendUnavailable("Tesseract executable not found")

    use_ocr_backend(monkeypatch, Missing)
    path = native_with_logo(tmp_path / "logo.pdf")
    doc = run(path, tmp_path / "out", canonical_version=version)
    routes = json.loads((tmp_path / "out/routes.json").read_text())
    assert routes["pages"][0]["route"] == "native_only"
    assert "REGION_OCR_UNAVAILABLE" in routes["pages"][0]["reasons"]
    assert any("stays publishable" in b["text"] for b in v1_blocks(doc))
    v1 = to_v1(doc) if version == 2 else doc
    assert [f["code"] for f in v1["pages"][0]["review"]] == ["REGION_OCR_UNAVAILABLE"]
    run_report = report(tmp_path / "out")
    assert run_report["status"] == "REVIEW"
    assert "PARTIAL_PAGES" in run_report["status_reasons"]
    assert run_report["unread_regions"] == 1


# IDP-009 / IDP-014 -----------------------------------------------------------


def test_native_document_passes_production_gate(tmp_path, fixed_ocr):
    path = native_pdf(tmp_path / "native.pdf", pages=2)
    run(path, tmp_path / "out")
    audit = json.loads((tmp_path / "out/canonical_audit.json").read_text())
    assert audit["pass"] and audit["production_pass"]
    assert report(tmp_path / "out")["trusted_parsers"]


def test_v1_paths_share_block_ids_and_evidence_fields(tmp_path, fixed_ocr):
    path = native_pdf(tmp_path / "native.pdf", pages=2)
    direct = run(path, tmp_path / "v1", canonical_version=1)
    view = to_v1(run(path, tmp_path / "v2", canonical_version=2))
    left, right = v1_blocks(direct), v1_blocks(view)
    assert [b["block_id"] for b in left] == [b["block_id"] for b in right]
    assert [b["text"] for b in left] == [b["text"] for b in right]
    assert [b["type"] for b in left] == [b["type"] for b in right]
    for a, b in zip(left, right):
        assert set(a["source_evidence"]) == set(b["source_evidence"])
        assert (
            a["source_evidence"]["verification_status"]
            == b["source_evidence"]["verification_status"]
        )
    again = run(path, tmp_path / "again", canonical_version=1)
    assert [b["block_id"] for b in v1_blocks(again)] == [b["block_id"] for b in left]


# IDP-010 / IDP-023 ---------------------------------------------------------


def test_cached_renders_do_not_spend_pixel_budget(tmp_path, fixed_ocr):
    from idp.runtime.cache import StageCache

    path = scan_pdf(tmp_path / "scan.pdf", pages=2)
    cache = tmp_path / "cache"
    for name in ("first", "second"):
        DeepDocService(
            DeepDocConfig(engine="unified", ocr_workers=1),
            stage_cache=StageCache(cache, max_backend_calls=50),
        ).process_pdf(path, tmp_path / name)
    assert report(tmp_path / "first")["render_pixels"] > 0
    assert report(tmp_path / "second")["render_pixels"] == 0


# IDP-012 -------------------------------------------------------------------


@pytest.mark.unit
def test_cache_identity_follows_stage_code(tmp_path, monkeypatch):
    import idp.runtime.cache as cache

    for name in cache.STAGE_MODULES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("v1")
    monkeypatch.setattr(cache, "PACKAGE_ROOT", tmp_path)
    monkeypatch.setattr(cache, "_IMPLEMENTATION", None)
    before = cache.implementation_sha256()
    (tmp_path / "pdf/render.py").write_text("v2")
    monkeypatch.setattr(cache, "_IMPLEMENTATION", None)
    assert cache.implementation_sha256() != before


@pytest.mark.unit
def test_cache_prune_removes_oldest_entries(tmp_path):
    from idp.runtime.cache import StageCache

    entries = tmp_path / "entries/render"
    entries.mkdir(parents=True)
    for i in range(5):
        path = entries / f"{i}.json"
        path.write_bytes(b"x" * 100)
        os.utime(path, (1000 + i, 1000 + i))
    cache = StageCache(tmp_path, max_bytes=250)
    assert cache.stats["pruned"] == 3
    assert sorted(p.name for p in entries.iterdir()) == ["3.json", "4.json"]


# IDP-016 -------------------------------------------------------------------


# IDP-017 -------------------------------------------------------------------


def test_hidden_layer_inside_form_xobject_is_detected(tmp_path):
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.profiling import profile_pages

    with fitz.open() as layer:
        page = layer.new_page(width=595, height=842)
        page.insert_text(
            (72, 100), "Invisible OCR layer text inside a form", render_mode=3
        )
        with fitz.open() as src:
            image = src.new_page(width=595, height=842)
            image.insert_text((72, 100), "Visible scan", fontsize=14)
            png = image.get_pixmap(dpi=72).tobytes("png")
        with fitz.open() as pdf:
            target = pdf.new_page(width=595, height=842)
            target.insert_image(target.rect, stream=png)
            target.show_pdf_page(target.rect, layer, 0)
            data = pdf.tobytes()
    with PdfSource(data) as source:
        native = PdfParsingEngine().extract_native(data, source=source)
        signal = profile_pages(native, source=source)[0]
    assert signal.hidden_layer_suspect is True
    assert signal.hidden_text_ratio == 1
