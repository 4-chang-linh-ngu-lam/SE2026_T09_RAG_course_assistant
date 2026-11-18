"""Regression tests for the unified PDF engine hardening (plan phases 2A-5).

Each test names the finding it pins down (F1..F12 of the post-Phase-1 review).
OCR is replaced by a deterministic echo backend that reads the PDF's own text
operators, so these run without Tesseract while still exercising the real
render -> acquisition -> merge -> finalize -> publication path.
"""

import ast
import hashlib
import json
import math
from pathlib import Path

import fitz
import pytest
from idp.evidence.contracts import DeepDocProducer
from idp.pdf import service as service_module
from idp.pdf.acquire import AcquisitionResult, OcrBlock
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import iter_retrievable_blocks, to_v1, validate_canonical

ROOT = Path(__file__).parents[1]


class EchoBackend:
    """Stand-in OCR: echoes each PDF text line (visible or not) at its box."""

    config_sha256 = "e" * 64
    mutate = None

    def __init__(self, out=None, config=None):
        pass

    def read(self, image, source, page, plan, *, deadline, target_region_id=None):
        frame = plan.frame
        w, h = frame.steps[-1].output_size
        blocks = []
        with fitz.open(stream=source.data, filetype="pdf") as doc:
            for b in doc[page - 1].get_text("dict")["blocks"]:
                for i, line in enumerate(b.get("lines", ())):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if not text:
                        continue
                    if self.mutate:
                        text = self.mutate(text)
                    x0, y0, x1, y1 = frame.from_pdf_pt(tuple(line["bbox"]))
                    box = (max(0, x0), max(0, y0), min(w, x1), min(h, y1))
                    blocks.append(OcrBlock(f"{b['number']}:{i}", text, box, 0.93))
        return AcquisitionResult(
            frame,
            DeepDocProducer("echo-ocr", "1"),
            "echo-family",
            self.config_sha256,
            "echo:raw",
            hashlib.sha256(image).hexdigest(),
            tuple(blocks),
        )


def run(path, out, **config):
    return DeepDocService(DeepDocConfig(engine="unified", **config)).process_pdf(
        path, out
    )


def v1_blocks(doc):
    if doc["schema_version"] == "idp-canonical-2":
        doc = to_v1(doc)
    return [b for p in doc["pages"] for b in p["blocks"]]


def scan_with_text_layer(path, lines, pages=1):
    with fitz.open() as src:
        page = src.new_page(width=595, height=842)
        for i, text in enumerate(lines):
            page.insert_text((72, 100 + i * 24), text, fontsize=14)
        png = page.get_pixmap(dpi=100).tobytes("png")
    with fitz.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=png)
            for i, text in enumerate(lines):
                page.insert_text((72, 100 + i * 24), text, fontsize=14, render_mode=3)
        pdf.save(path)
    return path


# F1 ------------------------------------------------------------------------


def test_clip_to_page_policy():
    from idp.pdf.native.geometry import clip_to_page

    assert clip_to_page((10, 10, 600, 20), 595, 842) == ((10, 10, 595, 20), True)
    assert clip_to_page((10, 10, 50, 20), 595, 842) == ((10, 10, 50, 20), False)
    assert clip_to_page((-5, -1, 50, 20), 595, 842) == ((0, 0, 50, 20), True)
    assert clip_to_page((600, 10, 650, 20), 595, 842) == (None, True)
    with pytest.raises(ValueError):
        clip_to_page((0, 0, math.inf, 1), 595, 842)


@pytest.mark.parametrize("version", [1, 2])
def test_text_bleeding_past_page_edge_does_not_fail_document(tmp_path, version):
    path = tmp_path / "bleed.pdf"
    with fitz.open() as pdf:
        for n in range(3):
            page = pdf.new_page(width=595.28, height=841.89)
            page.insert_text((72, 100), f"Ordinary body text on page {n + 1}.")
            # Runs past the right edge, as book bleed and edge folios do.
            page.insert_text(
                (430, 200), "This sentence continues well beyond the right margin."
            )
        pdf.save(path)
    doc = run(path, tmp_path / "out", canonical_version=version)
    blocks = v1_blocks(doc)
    # Poppler keeps the glyphs whose origin lies inside the crop box; the
    # block that bled past the edge is published with a clipped box.
    bleeding = [b for b in blocks if b["text"].startswith("This sentence continues")]
    assert len(bleeding) == 3 and all(b["bbox"][2] == 595.28 for b in bleeding)
    for b in blocks:
        x0, y0, x1, y1 = b["bbox"]
        assert 0 <= x0 < x1 <= 595.28 and 0 <= y0 < y1 <= 841.89
    report = json.loads((tmp_path / "out/run_report.json").read_text())
    assert "PDF_BBOX_CLIPPED" in report["diagnostics"]


# F2 ------------------------------------------------------------------------


def test_hidden_layer_ratio_not_any_operator():
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.profiling import profile_pages

    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        for i in range(12):
            page.insert_text((30, 60 + i * 20), f"Visible native body line number {i}")
        page.insert_text((30, 560), "tag", render_mode=3)
        data = doc.tobytes()
    with PdfSource(data) as source:
        native = PdfParsingEngine().extract_native(data, source=source)
        signal = profile_pages(native, source=source)[0]
    assert signal.hidden_layer_suspect is False
    assert 0 < signal.hidden_text_ratio < 0.05


@pytest.mark.parametrize("version", [1, 2])
def test_scan_with_agreeing_hidden_layer_is_published(tmp_path, monkeypatch, version):
    monkeypatch.setattr(service_module, "TesseractBackend", EchoBackend)
    lines = [
        "Let D be a nonempty set and f a function on D.",
        "The function f is bounded on D if some M exists.",
    ]
    path = scan_with_text_layer(tmp_path / "scan.pdf", lines, pages=2)
    doc = run(path, tmp_path / "out", canonical_version=version)
    routes = json.loads((tmp_path / "out/routes.json").read_text())
    assert {p["route"] for p in routes["pages"]} == {"ocr_page"}
    texts = [b["text"] for b in v1_blocks(doc)]
    assert texts.count(lines[0]) == 2 and texts.count(lines[1]) == 2
    if version == 2:
        published = list(iter_retrievable_blocks(doc))
        assert published
        assert {b["verification_status"] for b in published} == {
            "independent_agreement"
        }
        # Native text stays the source; OCR remains an alternative only.
        assert {b["origin"] for b in published} == {"NATIVE"}
    else:
        assert {
            b["source_evidence"]["verification_status"] for b in v1_blocks(doc)
        } == {"NATIVE_OCR_INDEPENDENT_AGREEMENT"}


def test_scan_with_disagreeing_hidden_layer_publishes_ocr_not_layer(
    tmp_path, monkeypatch
):
    """pdf-publication:5 (audit IDP-004): the hidden layer of an ``ocr_page``
    is unusable, so a confident OCR reading of the visible page is published
    as unverified OCR and the disagreeing layer stays withheld."""

    class Disagreeing(EchoBackend):
        mutate = staticmethod(lambda text: text.replace("bounded", "unbounded"))

    monkeypatch.setattr(service_module, "TesseractBackend", Disagreeing)
    lines = ["The function f is bounded on D if some M exists."]
    path = scan_with_text_layer(tmp_path / "scan.pdf", lines)
    doc = run(path, tmp_path / "out", canonical_version=2)
    published = list(iter_retrievable_blocks(doc))
    assert [b["text"] for b in published] == [lines[0].replace("bounded", "unbounded")]
    assert {(b["origin"], b["verification_status"]) for b in published} == {
        ("OCR", "ocr_unverified")
    }
    statuses = {b["verification_status"] for p in doc["pages"] for b in p["blocks"]}
    assert "independent_agreement" not in statuses


def test_disagreeing_hidden_layer_stays_in_review_under_policy_v4(
    tmp_path, monkeypatch
):
    from idp.pdf.publication import PublicationPolicy

    class Disagreeing(EchoBackend):
        mutate = staticmethod(lambda text: text.replace("bounded", "unbounded"))

    monkeypatch.setattr(service_module, "TesseractBackend", Disagreeing)
    lines = ["The function f is bounded on D if some M exists."]
    path = scan_with_text_layer(tmp_path / "scan.pdf", lines)
    doc = run(
        path,
        tmp_path / "out",
        canonical_version=2,
        publication=PublicationPolicy(version="pdf-publication:4"),
    )
    assert list(iter_retrievable_blocks(doc)) == []


# F3 ------------------------------------------------------------------------


def ruled_table(path):
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((60, 80), "Values of the function f(x) = 2x + 1 on [1, 3]:")
        xs, ys = [60, 160, 260, 360, 460], [100, 125, 150]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for i, t in enumerate(["x", "1", "2", "3"]):
            page.insert_text((xs[i] + 8, 118), t)
        for i, t in enumerate(["f(x)", "3", "5", "7"]):
            page.insert_text((xs[i] + 8, 143), t)
        page.insert_text((60, 180), "Remark: the function is increasing on the interval.")
        pdf.save(path)
    return path


def test_ruled_table_is_one_v1_table_block(tmp_path):
    doc = run(ruled_table(tmp_path / "t.pdf"), tmp_path / "out")
    blocks = v1_blocks(doc)
    tables = [b for b in blocks if b["type"] == "Table"]
    assert len(tables) == 1
    table = tables[0]
    assert table["text"] == "x | 1 | 2 | 3\nf(x) | 3 | 5 | 7"
    assert table["table_html"].startswith("<table><tr><td>x</td>")
    assert table["table_shape"] == [2, 4] and len(table["table_cells"]) == 8
    assert table["structured_status"] == "structure_unverified"
    # The 12 cell shards ("x", "1", ...) are no longer separate blocks.
    assert not any(b["type"] == "Text" and b["text"] in {"x", "1", "3"} for b in blocks)
    assert [b["type"] for b in blocks] == ["Text", "Table", "Text"]


def test_ruled_table_is_retrievable_and_citable_in_v2(tmp_path):
    from retrieval.canonical_harness import LocalRagIndex, resolve_citation

    doc = run(ruled_table(tmp_path / "t.pdf"), tmp_path / "out", canonical_version=2)
    published = list(iter_retrievable_blocks(doc))
    tables = [b for b in published if b["origin"] == "STRUCTURE"]
    assert len(tables) == 1
    assert tables[0]["verification_status"] == "structure_unverified"
    assert tables[0]["text"] == "x | 1 | 2 | 3\nf(x) | 3 | 5 | 7"
    shards = [
        b
        for p in doc["pages"]
        for b in p["blocks"]
        if "TABLE_CELL_FRAGMENT" in b["quality_reasons"]
    ]
    assert shards and not any(b["retrieval_eligible"] for b in shards)
    assert [b["type"] for b in to_v1(doc)["pages"][0]["blocks"]].count("Table") == 1
    index = LocalRagIndex(tmp_path / "rag.sqlite3")
    index.index(doc)
    hits = index.retrieve("f(x) 3 5 7", actor="a", access_check=lambda *a: True)
    assert hits and resolve_citation(hits[0], doc)


def test_formula_cue_in_prose_is_not_a_math_region():
    from idp.pdf.native.engine import PdfParsingEngine

    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        for i in range(30):
            page.insert_text(
                (60, 60 + i * 20),
                f"Line {i}: we know that a = b holds and also x/2 < y for this case.",
            )
        page.insert_text((60, 700), "x = 2y + 1")
        data = pdf.tobytes()
    record = PdfParsingEngine().extract_source(data)
    formulas = [
        r.trace.candidates[0].formula.native_text
        for r in record.manifest.structures.regions
        if r.trace.candidates[0].formula
    ]
    assert formulas == ["x = 2y + 1"]


# F4 ------------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 2])
def test_running_header_footer_and_folio_are_not_published(tmp_path, version):
    path = tmp_path / "book.pdf"
    with fitz.open() as pdf:
        for n in range(1, 5):
            page = pdf.new_page(width=595, height=842)
            page.insert_text((60, 40), "Calculus I - Chapter 2")
            page.insert_text((60, 300), f"Body paragraph that is unique to page {n}.")
            page.insert_text((60, 800), "Department of Mathematics")
            page.insert_text((290, 825), str(n))
        pdf.save(path)
    doc = run(path, tmp_path / "out", canonical_version=version)
    texts = [b["text"] for b in v1_blocks(doc)]
    assert texts == [f"Body paragraph that is unique to page {n}." for n in range(1, 5)]
    record = json.loads((tmp_path / "out/extraction.json").read_text(encoding="utf-8"))
    assert "Calculus I - Chapter 2" in json.dumps(record)  # kept in L1


# F5 / 2C -------------------------------------------------------------------


def test_v2_references_l1_instead_of_embedding_it(tmp_path):
    import shutil

    from idp import publish

    native = ROOT / "tests/fixtures/generated/native.pdf"
    doc = run(native, tmp_path / "out", canonical_version=2)
    extraction = tmp_path / "out/extraction.json"
    assert doc["l1_payload"] is None and doc["l1_ref"] == "extraction.json"
    assert doc["l1_sha256"] == hashlib.sha256(extraction.read_bytes()).hexdigest()
    # Location-independent: the same input in another folder is identical.
    assert run(native, tmp_path / "elsewhere", canonical_version=2) == doc

    def cold():
        publish._RECORDS.clear()
        publish._VALIDATED.clear()

    cold()
    stored = json.loads((tmp_path / "out/canonical.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="load_canonical"):
        validate_canonical(stored)  # no L1 in memory and no folder given
    moved = tmp_path / "moved"
    shutil.copytree(tmp_path / "out", moved)
    from idp.publish import load_canonical

    cold()
    assert list(iter_retrievable_blocks(load_canonical(moved / "canonical.json")))
    tampered = moved / "extraction.json"
    tampered.write_bytes(tampered.read_bytes().replace(b"Independent", b"Invented!!!"))
    cold()
    with pytest.raises(ValueError, match="L1"):
        load_canonical(moved / "canonical.json")
    tampered.unlink()
    cold()
    with pytest.raises(ValueError, match="L1"):
        load_canonical(moved / "canonical.json")
    for bad in ("../extraction.json", "/etc/passwd", r"C:\x.json", "sub/extraction.json"):
        forged = {**stored, "l1_ref": bad}
        cold()
        with pytest.raises(ValueError):
            validate_canonical(forged, base_dir=moved)


def test_validation_cache_never_hides_a_mutation(tmp_path):
    doc = run(ROOT / "tests/fixtures/generated/native.pdf", tmp_path / "out", canonical_version=2)
    assert list(iter_retrievable_blocks(doc))
    doc["pages"][0]["blocks"][0]["text"] = "Hallucinated"
    with pytest.raises(ValueError):
        list(iter_retrievable_blocks(doc))


def test_previous_policy_versions_still_validate(tmp_path):
    """Stored canonicals from the previous policy pair stay valid."""
    from idp.pdf.publication import PublicationPolicy
    from idp.publish import PublishPolicy, project_v2

    doc = run(
        ruled_table(tmp_path / "t.pdf"),
        tmp_path / "out",
        canonical_version=2,
        publication=PublicationPolicy(version="pdf-publication:2"),
    )
    assert doc["publication_inputs"]["policy"]["version"] == "pdf-publication:2"
    validate_canonical(doc)
    assert not any(b["origin"] == "STRUCTURE" for b in iter_retrievable_blocks(doc))
    with pytest.raises(ValueError, match="idp-publish:2"):
        project_v2(
            None,
            None,
            None,
            (),
            "x",
            policy=PublishPolicy(version="idp-publish:1"),
            publication_policy=PublicationPolicy(),
        )


def test_contract_guard_rejects_foreign_objects_and_caches_frozen_idp():
    from idp.pdf.native import result

    class Foreign:
        pass

    Foreign.__module__ = "parser.pdf.contracts"
    with pytest.raises(TypeError):
        result.validate_idp_contracts(({"k": [Foreign()]},))
    producer = DeepDocProducer("x", "1")
    result.validate_idp_contracts((producer,))
    assert result._VALIDATED.get(id(producer)) is producer
    result.reset_contract_cache()
    assert not result._VALIDATED


def test_no_idp_module_imports_parser():
    """Static form of the runtime guard (F11)."""
    offenders = []
    for path in (ROOT / "idp").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )
            if any(n == "parser" or n.startswith("parser.") for n in names):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# OCR retry -----------------------------------------------------------------


def test_retry_only_when_render_scale_can_increase():
    from idp.pdf.native.preflight import PdfSource

    data = (ROOT / "tests/fixtures/generated/native.pdf").read_bytes()
    with PdfSource(data) as source:
        capped = DeepDocService(DeepDocConfig(engine="unified", max_pixels=1_000_000))
        assert not capped._retry_scales_up(source, 1)
        roomy = DeepDocService(DeepDocConfig(engine="unified", max_pixels=16_000_000))
        assert roomy._retry_scales_up(source, 1)


# OCR render quality ----------------------------------------------------------


def test_coarse_scan_is_rendered_native_then_smoothly_upscaled():
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_for_ocr

    fixtures = ROOT / "tests/fixtures/generated"
    with PdfSource((fixtures / "scan.pdf").read_bytes()) as source:
        data, frame = render_for_ocr(source, 1, dpi=216, max_pixels=4_000_000)
        # 400x600 pt page holding a 400x600 px (72 dpi) scan.
        assert [s.kind for s in frame.steps] == ["render", "resize"]
        assert frame.steps[0].output_size == (400, 600)
        assert frame.steps[-1].output_size == (1200, 1800)
        assert hashlib.sha256(data).hexdigest() == frame.steps[-1].output_sha256
        # Coordinates still map exactly back to PDF points.
        assert frame.to_pdf_pt((300, 450, 600, 900)) == pytest.approx((100, 150, 200, 300))
    with PdfSource((fixtures / "native.pdf").read_bytes()) as source:
        _, frame = render_for_ocr(source, 1, dpi=216, max_pixels=4_000_000)
        assert [s.kind for s in frame.steps] == ["render"]  # no dominant raster


def test_high_resolution_scan_is_rendered_directly(tmp_path):
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_for_ocr

    with fitz.open() as src:
        page = src.new_page(width=400, height=600)
        page.insert_text((40, 80), "Sharp source raster", fontsize=12)
        png = page.get_pixmap(dpi=300).tobytes("png")
    with fitz.open() as pdf:
        pdf.new_page(width=400, height=600).insert_image(fitz.Rect(0, 0, 400, 600), stream=png)
        data = pdf.tobytes()
    with PdfSource(data) as source:
        _, frame = render_for_ocr(source, 1, dpi=216, max_pixels=4_000_000)
    assert [s.kind for s in frame.steps] == ["render"]


@pytest.mark.skipif(
    __import__("shutil").which("tesseract") is None, reason="real Tesseract required"
)
@pytest.mark.parametrize("backend", ["tesseract", "legacy-hybrid"])
def test_real_ocr_reads_coarse_scan_like_legacy(tmp_path, backend):
    # Ground truth comes from tests/fixtures/generate.py, never from the PDF.
    truth = [
        "Phase zero document. Native source evidence for regression.",
        "Independent expected text. Page number 1.",
    ]
    doc = run(
        ROOT / "tests/fixtures/generated/scan.pdf",
        tmp_path / "out",
        canonical_version=2,
        language="eng",
        ocr_backend=backend,
    )
    texts = [b["text"] for p in doc["pages"] for b in p["blocks"] if b["origin"] == "OCR"]
    assert texts == truth
    published = [b["text"] for b in iter_retrievable_blocks(doc)]
    assert published == truth


# Phase 3 -------------------------------------------------------------------


@pytest.mark.parametrize("backend,expected", [("legacy-hybrid", 0.91), ("marker", 0)])
def test_legacy_hybrid_adapter_keeps_real_confidence(tmp_path, backend, expected):
    from idp.ocr.backends.advanced import AdvancedBackend
    from idp.pdf.acquire import AcquisitionRequest
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    class Recorded:
        identity = {"backend": backend, "unit": "recorded"}

        def execute(self, image_bytes, *, deadline):
            return {
                "schema": "deepdoc-model-result:1",
                "backend": backend,
                "packages": {"unit": "1"},
                "weights_sha256": {},
                "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "raw": {
                    "metadata": {"engine": "tesseract_fallback"},
                    "children": [
                        {
                            "block_type": "Page",
                            "bbox": [0, 0, 800, 1200],
                            "children": [
                                {
                                    "block_type": "Text",
                                    "bbox": [10, 10, 400, 60],
                                    "html": "<p>Paragraph read by legacy OCR</p>",
                                    "_idp_confidence": 91,
                                }
                            ],
                        }
                    ],
                },
            }

    Recorded.backend = backend
    with PdfSource((ROOT / "tests/fixtures/generated/scan.pdf").read_bytes()) as source:
        image, frame = render_page(source, 1)
        result = AdvancedBackend(tmp_path, Recorded()).read(
            image, source, 1, AcquisitionRequest("k", frame), deadline=1e20
        )
    (block,) = result.blocks
    assert block.text == "Paragraph read by legacy OCR"
    assert block.confidence == pytest.approx(expected)
    assert block.payload["recognition_confidence_available"] is (expected > 0)


def test_legacy_hybrid_registered_and_preferred_by_auto(monkeypatch):
    from idp.evidence.contracts import DeepDocCapability as C

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    registry = DeepDocService(DeepDocConfig(engine="unified"))._default_registry()
    assert registry.select_acquisition("auto", (C.TEXT,)).name == "legacy-hybrid"
    assert DeepDocConfig(ocr_backend="legacy-hybrid").ocr_backend == "legacy-hybrid"


# Phase 4 -------------------------------------------------------------------


def shadow(sha, legacy_chars, unified_chars, jaccard, review=0, status="compared"):
    summary = lambda chars: {"characters": chars, "pages": 10, "tables": 0}
    return {
        "schema": "deepdoc-shadow:1",
        "status": status,
        "source_sha256": sha,
        "legacy": summary(legacy_chars),
        "unified": summary(unified_chars),
        "shingle_jaccard": jaccard,
        "unified_report": {"review_pages": list(range(review))},
    }


def test_cutover_gate_passes_only_on_sufficient_agreeing_corpus():
    from idp.pdf.cutover import ShadowGate, evaluate

    gate = ShadowGate(min_documents=3)
    good = [shadow(f"{i:064x}", 1000, 995, 0.97) for i in range(3)]
    assert evaluate(good, gate)["passed"]
    assert "CORPUS_TOO_SMALL:2<3" in evaluate(good[:2], gate)["reasons"]
    failed = [*good, shadow("f" * 64, 1000, 0, None, status="unified_failed")]
    assert not evaluate(failed, gate)["passed"]
    lossy = [*good[:2], shadow("a" * 64, 1000, 500, 0.5)]
    reasons = evaluate(lossy, gate)["reasons"]
    assert "DOCUMENTS_LOSING_TEXT:1" in reasons
    review = [shadow(f"{i:064x}", 1000, 1000, 0.99, review=5) for i in range(3)]
    assert "REVIEW_PAGE_REGRESSION" in evaluate(review, gate)["reasons"]


def test_shadow_run_feeds_cutover_gate(tmp_path):
    from idp.pdf.cutover import ShadowGate, evaluate, load_diffs

    DeepDocService(DeepDocConfig(engine="shadow")).process_pdf(
        ROOT / "tests/fixtures/generated/native.pdf", tmp_path / "out"
    )
    diffs = list(load_diffs([tmp_path]))
    assert len(diffs) == 1 and 0 <= diffs[0]["shingle_jaccard"] <= 1
    report = evaluate(diffs, ShadowGate(min_documents=1))
    assert report["metrics"]["documents"] == 1


def test_tsv_word_that_is_a_quote_does_not_swallow_the_page():
    """A lone '"' word must not open a csv quoted field (real SGK page 1 bug)."""
    from idp.ocr.backends.tesseract import parse_tsv

    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    rows = (
        "2\t1\t1\t0\t0\t0\t10\t10\t300\t20\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t40\t20\t95\tBỘ\n"
        "5\t1\t1\t1\t1\t2\t60\t10\t40\t20\t95\tGIAO\n"
        "5\t1\t1\t1\t2\t1\t10\t40\t9\t20\t55.9\t\"\n"
        "5\t1\t1\t1\t3\t1\t10\t70\t60\t20\t92\tDỤC\n"
    )
    blocks = parse_tsv((header + rows).encode("utf-8"), (400, 400))
    texts = sorted(b.text for b in blocks)
    assert texts == ['"', "BỘ GIAO", "DỤC"]
    assert all("\t" not in b.text and "\n" not in b.text for b in blocks)


# OCR quality and throughput (measured on hand-transcribed SGK pages) ---------


def test_tone_step_is_recorded_and_keeps_coordinates():
    from io import BytesIO

    from PIL import Image
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_for_ocr, tone_normalize

    with PdfSource((ROOT / "tests/fixtures/generated/scan.pdf").read_bytes()) as source:
        data, frame = render_for_ocr(source, 1, dpi=216, max_pixels=4_000_000)
        toned, toned_frame = tone_normalize(data, frame)
    assert toned_frame.steps[-1].kind == "tone"
    assert toned_frame.steps[-1].output_sha256 == hashlib.sha256(toned).hexdigest()
    assert toned_frame.to_pdf_pt((300, 450, 600, 900)) == frame.to_pdf_pt((300, 450, 600, 900))
    with Image.open(BytesIO(toned)) as image:
        assert image.mode == "L" and image.size == frame.steps[-1].output_size


def test_frame_dpi_is_the_real_render_resolution():
    from idp.ocr.backends.tesseract import frame_dpi
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_for_ocr

    with PdfSource((ROOT / "tests/fixtures/generated/scan.pdf").read_bytes()) as source:
        _, frame = render_for_ocr(source, 1, dpi=216, max_pixels=4_000_000)
    assert frame_dpi(frame) == 216


def test_non_tsv_tesseract_output_fails_loudly():
    from idp.ocr.backends.tesseract import parse_tsv

    with pytest.raises(ValueError, match="TSV"):
        parse_tsv("Plain text because configs/tsv is missing\n".encode(), (100, 100))
    assert parse_tsv(b"", (100, 100)) == ()


def test_tesseract_lines_group_into_paragraphs_only_for_line_keys():
    from idp.pdf.acquire import group_paragraphs
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    with PdfSource((ROOT / "tests/fixtures/generated/scan.pdf").read_bytes()) as source:
        _, frame = render_page(source, 1)

    def result(blocks):
        return AcquisitionResult(
            frame, DeepDocProducer("t", "1"), "t", "0" * 64, "r", "1" * 64, tuple(blocks)
        )

    lines = [
        OcrBlock("1:1:1:1", "Dòng một", (10, 10, 100, 20), 0.9),
        OcrBlock("1:1:1:2", "dòng hai", (10, 22, 120, 32), 0.7),
        OcrBlock("1:1:2:1", "Đoạn khác", (10, 50, 90, 60), 0.95),
    ]
    grouped = group_paragraphs(result(lines))
    assert [b.text for b in grouped.blocks] == ["Dòng một\ndòng hai", "Đoạn khác"]
    assert grouped.blocks[0].bbox_px == (10, 10, 120, 32)
    assert 0.7 < grouped.blocks[0].confidence < 0.9
    other = result([OcrBlock("marker-7", "x", (1, 1, 5, 5), 0.9)])
    assert group_paragraphs(other) is other


def test_language_auto_probe_picks_vie_only_for_vietnamese(tmp_path, monkeypatch):
    from idp.pdf.service import legacy_language, vietnamese_ratio

    monkeypatch.setattr(service_module, "TesseractBackend", EchoBackend)
    assert legacy_language("auto") == "vie+eng" and legacy_language("eng") == "eng"
    assert vietnamese_ratio("Bất phương trình bậc nhất")[0] > 0.2
    assert vietnamese_ratio("Independent expected text")[0] == 0
    font = next(
        p for p in (Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        if p.is_file()
    )
    for name, lines, expected in (
        ("vi", ["Cho tập hợp D khác rỗng và hàm số f xác định trên D."] * 12, "vie"),
        ("en", ["Let D be a nonempty set and f a function defined on D."] * 12, "vie+eng"),
    ):
        path = tmp_path / f"{name}.pdf"
        with fitz.open() as src:
            page = src.new_page(width=595, height=842)
            page.insert_font(fontname="u", fontfile=str(font))
            for i, text in enumerate(lines):
                page.insert_text((60, 80 + i * 22), text, fontname="u", fontsize=12)
            png = page.get_pixmap(dpi=100).tobytes("png")
        with fitz.open() as pdf:
            page = pdf.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=png)
            pdf.save(path)
        # Echo reads the PDF text layer; give the scan an invisible one.
        with fitz.open(path) as pdf:
            pdf[0].insert_font(fontname="u", fontfile=str(font))
            for i, text in enumerate(lines):
                pdf[0].insert_text((60, 80 + i * 22), text, fontname="u", fontsize=12, render_mode=3)
            pdf.saveIncr()
        run(path, tmp_path / name)
        report = json.loads((tmp_path / name / "run_report.json").read_text())
        assert report["ocr_language_decision"]["language"] == expected


def test_ocr_folios_and_running_headers_are_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "TesseractBackend", EchoBackend)
    path = tmp_path / "scan.pdf"
    with fitz.open() as pdf:
        for n in range(1, 5):
            with fitz.open() as src:
                page = src.new_page(width=595, height=842)
                png = page.get_pixmap(dpi=72).tobytes("png")
            page = pdf.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=png)
            page.insert_text((60, 40), "Calculus I Chapter Two", render_mode=3)
            page.insert_text((60, 400), f"Body paragraph that is unique to page {n}.", render_mode=3)
            page.insert_text((290, 820), str(n + 20), render_mode=3)
        pdf.save(path)
    doc = run(path, tmp_path / "out", canonical_version=2, language="eng")
    published = [b["text"] for b in iter_retrievable_blocks(doc)]
    assert published == [f"Body paragraph that is unique to page {n}." for n in range(1, 5)]


def test_parallel_ocr_is_deterministic(tmp_path, monkeypatch):
    class ParallelEcho(EchoBackend):
        parallel_safe = True

    monkeypatch.setattr(service_module, "TesseractBackend", ParallelEcho)
    lines = ["Let D be a nonempty set and f a function on D."]
    path = scan_with_text_layer(tmp_path / "scan.pdf", lines, pages=6)
    serial = run(path, tmp_path / "serial", canonical_version=2, language="eng", ocr_workers=1)
    parallel = run(path, tmp_path / "parallel", canonical_version=2, language="eng", ocr_workers=4)
    assert serial == parallel
