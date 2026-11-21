"""Regression tests for round 2 of the 2026-11-19 IDP audit (services/rag/idp/pdf)."""

import re
import threading
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from test_unified_hardening import ruled_table, run, v1_blocks

IDP = Path(__file__).resolve().parents[1] / "idp"


# --- #1 / #3 tables: withheld grid falls back to its cells, no duplicates ----

def test_furniture_cell_does_not_withhold_the_grid(tmp_path, monkeypatch):
    from idp.pdf import publication

    original = publication.furniture_sources

    def header_row_is_furniture(record):
        found = original(record)
        return found | {o.source_id for o in record.observations if (o.text or "").strip() == "x"}

    monkeypatch.setattr(publication, "furniture_sources", header_row_is_furniture)
    blocks = v1_blocks(run(ruled_table(tmp_path / "t.pdf"), tmp_path / "out"))
    tables = [b for b in blocks if b["type"] == "Table"]
    assert len(tables) == 1 and tables[0]["text"].startswith("x | 1")


def test_withheld_grid_publishes_its_clean_cells(tmp_path, monkeypatch):
    from idp.pdf import publication

    original = publication.table_sources

    def one_partial_contributor(record, tables=None):
        shards, contributors = original(record, tables)
        partial = sorted(shards)[0]
        return {k: v for k, v in shards.items() if k != partial}, contributors

    monkeypatch.setattr(publication, "table_sources", one_partial_contributor)
    doc = run(ruled_table(tmp_path / "t.pdf"), tmp_path / "out")
    blocks = v1_blocks(doc)
    assert not any(b["type"] == "Table" for b in blocks)
    texts = {b["text"] for b in blocks}
    assert {"f(x)", "7"} <= texts
    decisions = __import__("json").loads((tmp_path / "out/publication.json").read_text(encoding="utf-8"))["decisions"]
    table = [d for d in decisions if d["status"] == publication.TABLE_STATUS]
    assert table and "TABLE_PARTIAL_SOURCE_BLOCK" in table[0]["reasons"]
    assert not any("TABLE_CELL_FRAGMENT" in d["reasons"] for d in decisions)


# --- #2 corrected glyphs inside table cells ---------------------------------

def test_cell_text_applies_recovery_edits():
    from idp.pdf.tables import cell_text, span_text

    edit = SimpleNamespace(start=2, end=4, replacement="≠")
    edits = {"raw": (edit,)}
    whole = SimpleNamespace(candidate_id="raw", start=0, end=6, text="a 6= b")
    assert span_text(whole, edits) == "a ≠ b"
    left = SimpleNamespace(candidate_id="raw", start=0, end=3, text="a 6")
    right = SimpleNamespace(candidate_id="raw", start=3, end=6, text="= b")
    assert span_text(left, edits) + span_text(right, edits) == "a ≠ b"
    assert cell_text(SimpleNamespace(source_spans=(whole,)), edits) == "a ≠ b"
    assert cell_text(SimpleNamespace(source_spans=(whole,))) == "a 6= b"


# --- #4 running headers vs numbered headings ---------------------------------

def _ocr_item(text, page):
    return SimpleNamespace(text=text, locations=(SimpleNamespace(page=page),))


def test_numbered_headings_are_not_running_headers():
    from idp.pdf.publication import _running_numbers

    assert not _running_numbers([_ocr_item(f"Chương {n}", p) for n, p in ((1, 3), (2, 9), (3, 20))])
    assert _running_numbers([_ocr_item("Toán 10", p) for p in (3, 4, 5)])
    assert _running_numbers([_ocr_item(f"Toán - Trang {p + 10}", p) for p in (3, 4, 5)])


# --- #6 every REVIEW route reason surfaces in page["review"] -------------------

def test_every_review_route_reason_has_a_page_flag():
    from idp.pdf.projector import PAGE_REVIEW_REASONS, page_review_flags

    router = (IDP / "pdf/router.py").read_text(encoding="utf-8")
    reasons = set(re.findall(r'PageRoute\.REVIEW, \(?"([A-Z_]+)"', router))
    reasons |= {"OUTSIDE_REQUESTED_SCOPE"}
    assert {"OCR_BACKEND_UNAVAILABLE", "SPARSE_UNCERTAIN_NATIVE"} <= reasons
    assert reasons <= set(PAGE_REVIEW_REASONS)
    assert page_review_flags(("OCR_BACKEND_UNAVAILABLE",))[0]["severity"] == "error"


# --- #7 invalid proposal geometry is reviewed, not fatal -----------------------

def test_invalid_pixel_boxes_are_rejected():
    from idp.pdf.understanding import _valid_pixel_box

    assert _valid_pixel_box([1, 1, 10, 10], (20, 20))
    for box in ([10, 1, 1, 10], [1, 1, 30, 10], [0, 0, float("nan"), 1], "bad"):
        assert not _valid_pixel_box(box, (20, 20))


# --- #8 contract cache under threads -------------------------------------------

def test_contract_cache_survives_concurrent_resets():
    from idp.evidence.contracts import DeepDocDiagnostic
    from idp.pdf.native.result import reset_contract_cache, validate_idp_contracts

    errors = []

    def work():
        try:
            for i in range(300):
                validate_idp_contracts((DeepDocDiagnostic("CODE", f"m{i}"),))
                if i % 50 == 0:
                    reset_contract_cache()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


# --- #10 region budget scales with pages -------------------------------------

def test_region_budget_scales_per_page():
    from idp.pdf.service import DeepDocConfig

    cfg = DeepDocConfig(engine="unified")
    assert cfg.effective_limits(300)["max_regions"] == 300 * cfg.max_regions
    assert DeepDocConfig(engine="unified", budget_mode="absolute").effective_limits(300)["max_regions"] == cfg.max_regions


# --- #11 scan inside a Form XObject ------------------------------------------------

def test_dominant_image_scale_applies_form_matrix(tmp_path):
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import dominant_image_scale

    with fitz.open() as inner:
        page = inner.new_page(width=200, height=200)
        page.insert_image(page.rect, pixmap=fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 0))
        with fitz.open() as outer:
            target = outer.new_page(width=100, height=100)
            target.show_pdf_page(target.rect, inner, 0)
            data = outer.tobytes()
    with PdfSource(data) as source:
        assert dominant_image_scale(source, 1) == pytest.approx(2.0, rel=0.01)


# --- #12 lazily parsed broken content stream -----------------------------------------

def test_count_shown_survives_lazy_parse_errors():
    from idp.pdf.profiling import _count_shown

    class Broken:
        @property
        def operations(self):
            raise ValueError("bad content stream")

    source = SimpleNamespace(check_deadline=lambda: 1)
    assert _count_shown(source, Broken(), {}) == (0, 0)


# --- #13 several verifiers for one capability ----------------------------------

def test_registry_select_uses_request_identity():
    from idp.pdf.verify_runtime import BackendRegistry

    cpu = SimpleNamespace(available=True, capabilities=("MATH",), producer="p-cpu", family="f", resource="CPU")
    gpu = SimpleNamespace(available=True, capabilities=("MATH",), producer="p-gpu", family="f", resource="GPU")
    registry = BackendRegistry.__new__(BackendRegistry)
    registry.backends = [cpu, gpu]
    assert registry.select("MATH", "p-gpu", "f", "GPU") is gpu
    with pytest.raises(LookupError):
        registry.select("MATH")


# --- #17 partial recoveries stay suspect --------------------------------------------

def test_partial_recovery_is_not_proof_recovered():
    from idp.pdf.profiling import _proof_recovered

    proof = SimpleNamespace(character_code_hex="36", glyph_name="/negationslash")
    evidence = SimpleNamespace(id="e", glyph_proofs=(proof,), review=None)
    selected = SimpleNamespace(id="sel", evidence_ids=("e",))
    item = SimpleNamespace(extraction=SimpleNamespace(
        source_candidate_id="sel", raw_candidate_id="raw", candidates=(selected,), evidence=(evidence,)))
    mapped = SimpleNamespace(code="PDF_FONT_GLYPH_MAPPING_SUSPECT", status="SUSPECT", character_code_hex="36", glyph_name=None)
    leftover = SimpleNamespace(code="PDF_SECONDARY_TEXT_UNASSIGNED", status="SUSPECT", character_code_hex=None, glyph_name=None)
    assert _proof_recovered(item, [mapped])
    assert not _proof_recovered(item, [mapped, leftover])


# --- #19 / #20 glyph and table geometry ----------------------------------------------

def test_null_differences_and_form_fonts():
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NullObject, NumberObject

    from idp.pdf.native.glyph.inspector import _encoding_differences

    assert _encoding_differences(DictionaryObject({NameObject("/Differences"): NullObject()})) == []
    diffs = ArrayObject([NumberObject(48), NullObject(), NameObject("/prime")])
    assert _encoding_differences(DictionaryObject({NameObject("/Differences"): diffs})) == [(48, "/prime")]


def test_text_in_form_xobject_is_inspected(tmp_path):
    from idp.pdf.native.glyph.inspector import PdfGlyphInspector

    with fitz.open() as inner:
        page = inner.new_page(width=200, height=100)
        page.insert_text((20, 50), "inside a form", fontsize=12)
        with fitz.open() as outer:
            target = outer.new_page(width=200, height=100)
            target.show_pdf_page(target.rect, inner, 0)
            data = outer.tobytes()
    inspection = PdfGlyphInspector().inspect(data, suspicious_pages={1}, pages_to_inspect={1})
    assert any(font.resource_name.startswith("form") for font in inspection.font_resources)
    assert inspection.code_uses


def test_tex_font_under_two_resource_keys_is_one_font():
    from idp.pdf.native.glyph.tex import _font_for_char

    def font(fingerprint):
        return SimpleNamespace(
            normalized_base_font="CMSY10", difference_map={48: "/prime"}, to_unicode_codes=(),
            font_fingerprint=fingerprint, embedded_font_sha256=None, encoding_sha256="e",
            to_unicode_sha256=None, subtype="/Type1",
        )

    chosen, glyph = _font_for_char([font("b"), font("a")], "CMSY10", 48)
    assert glyph == "/prime" and chosen.font_fingerprint == "a"


def test_inverted_mediabox_equals_cropbox():
    from idp.pdf.native.extractors.table import _media_is_crop

    reader_page = SimpleNamespace(mediabox=(600, 800, 0, 0))
    source = SimpleNamespace(
        reader=SimpleNamespace(pages=[reader_page]),
        geometry={1: SimpleNamespace(crop_box=(0.0, 0.0, 600.0, 800.0))},
    )
    assert _media_is_crop(SimpleNamespace(page_number=1), source)


# --- regression found by the real-book benchmark ---------------------------------

def test_glyphs_outside_every_block_never_gate_other_blocks():
    """A page-wide SUSPECT TeX finding withheld every block of 29 pages
    (1230 blocks) of a 141-page book; it is recorded but non-gating."""
    from idp.pdf.native.scoping import NON_GATING_CODES, finding_targets

    assert "PDF_TEX_GLYPH_OUTSIDE_NATIVE_BLOCKS" in NON_GATING_CODES
    finding = SimpleNamespace(
        id="f", code="PDF_TEX_GLYPH_OUTSIDE_NATIVE_BLOCKS", status="SUSPECT", scope="PAGE", source_id=None,
        page=1, operator_index=None, string_index=None, code_index=None, resource_scope=None,
        raw_extracted_text=None, unicode_mapping=None, character_code_hex=None, glyph_name=None,
    )
    assert finding_targets([finding], {1: [("pdf:text:1:0", "text")]})["f"] == frozenset()
