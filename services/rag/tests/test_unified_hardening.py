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
from idp_test_backends import use_ocr_backend
from idp.evidence.contracts import DeepDocProducer
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
    use_ocr_backend(monkeypatch, EchoBackend)
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

    use_ocr_backend(monkeypatch, Disagreeing)
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


# Phase 3 -------------------------------------------------------------------


# Phase 4 -------------------------------------------------------------------


# OCR quality and throughput (measured on hand-transcribed SGK pages) ---------


def test_ocr_folios_and_running_headers_are_not_published(tmp_path, monkeypatch):
    use_ocr_backend(monkeypatch, EchoBackend)
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
    doc = run(path, tmp_path / "out", canonical_version=2)
    published = [b["text"] for b in iter_retrievable_blocks(doc)]
    assert published == [f"Body paragraph that is unique to page {n}." for n in range(1, 5)]


def test_parallel_ocr_is_deterministic(tmp_path, monkeypatch):
    class ParallelEcho(EchoBackend):
        parallel_safe = True

    use_ocr_backend(monkeypatch, ParallelEcho)
    lines = ["Let D be a nonempty set and f a function on D."]
    path = scan_with_text_layer(tmp_path / "scan.pdf", lines, pages=6)
    serial = run(path, tmp_path / "serial", canonical_version=2, ocr_workers=1)
    parallel = run(path, tmp_path / "parallel", canonical_version=2, ocr_workers=4)
    assert serial == parallel
