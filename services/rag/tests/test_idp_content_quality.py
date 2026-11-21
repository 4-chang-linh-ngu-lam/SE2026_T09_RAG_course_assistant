"""Content-quality fixes from the 2026-11-18 benchmark reviews.

* ``ban_chinh_sua_final.pdf`` (TeX, native text): one page/font finding
  withheld a whole page of correct prose; primes/integrals/delimiters were
  published as ``0``/``Z``/control characters; folios on the running-header
  line leaked; a two-column exercise list was read row by row.
* ``SGK Toán 10`` (scan, Tesseract): misread formula/icon tokens and
  partial data rows were published.

Real-document measurements are in
``docs/deepdoc/benchmarks/content-quality-fixes/README.md``.
"""

from types import SimpleNamespace

import pytest
from idp.evidence.contracts import (
    DeepDocBoundingBox,
    DeepDocGlyphFinding,
    DeepDocGlyphNameProof,
    DeepDocSourceLocation,
)
from idp.pdf.native.glyph.backend import PdfiumCharacter
from idp.pdf.native.glyph.inspector import PdfFontMetadata
from idp.pdf.native.glyph.repair import apply_verified_font_glyph_correction
from idp.pdf.native.glyph.tex import propose_tex_glyph_corrections, tex_glyph
from idp.pdf.native.layout import PdfLayoutPolicy, _Box, _page_flow
from idp.pdf.native.scoping import finding_targets
from idp.pdf.publication import PublicationPolicy, folio_series_sources


def finding(code, status="SUSPECT", scope="FONT_RESOURCE", **kw):
    payload = dict(page=33, font_evidence_ids=("font:1",) if scope == "FONT_RESOURCE" else ())
    payload.update(kw)
    if scope == "REGION":
        payload.update(candidate_ids=("candidate:a",), evidence_ids=("evidence:a",))
    return DeepDocGlyphFinding("finding:" + code + str(len(kw)), code, status, scope, "reason", **payload)


TEXTS = {
    33: [
        ("pdf:text:33:4", "Trường hợp 3: Thừa số tích phân là hàm hợp"),
        ("pdf:text:33:55", "∂M ∂N 6 = nên phương trình đã cho"),
        ("pdf:text:33:62", "(2.5.10)"),
    ]
}


def test_font_finding_only_affects_blocks_holding_its_character():
    """A negationslash code read as "6" can only sit in a block with a 6."""
    f = finding("PDF_FONT_GLYPH_MAPPING_SUSPECT", raw_extracted_text="6", character_code_hex="36")
    assert finding_targets([f], TEXTS)[f.id] == {"pdf:text:33:55"}


def test_unlocatable_findings_stay_page_wide_and_coverage_does_not_gate():
    nowhere = finding("PDF_FONT_GLYPH_MAPPING_SUSPECT", raw_extracted_text="§")
    page = finding("PDF_GLYPH_SECONDARY_BACKEND_UNAVAILABLE", scope="PAGE")
    outside = finding("PDF_SECONDARY_TEXT_OUTSIDE_NATIVE_BLOCKS", scope="PAGE")
    region = finding("PDF_TEXT_CONTROL_CHARACTER", scope="REGION", source_id="pdf:text:33:62")
    targets = finding_targets([nowhere, page, outside, region], TEXTS)
    assert targets[nowhere.id] is None and targets[page.id] is None
    assert targets[outside.id] == frozenset()
    assert targets[region.id] == {"pdf:text:33:62"}


def test_suspect_code_use_that_the_inspector_verified_is_resolved():
    position = dict(raw_extracted_text="6", character_code_hex="36", resource_scope="page:33:/F30", operator_index=7, string_index=0, code_index=2)
    suspect = finding("PDF_FONT_GLYPH_MAPPING_SUSPECT", **position)
    verified = finding("PDF_FONT_GLYPH_RECOVERY_VERIFIED", status="VERIFIED", **position)
    assert finding_targets([suspect, verified], TEXTS)[suspect.id] == frozenset()


def obs(source_id, page, box, text, *, ocr=True, lines=1, run=None, height=842.0):
    payload = {"lines": lines}
    if run:
        payload["column_run"] = run
    return SimpleNamespace(
        source_id=source_id,
        text=text,
        kind=SimpleNamespace(value="TEXT"),
        extraction_source=SimpleNamespace(value="OCR" if ocr else "NATIVE"),
        locations=(DeepDocSourceLocation(page, 595.0, height, DeepDocBoundingBox(*box)),),
        attributes={"recognition": {"payload": payload}},
    )


def test_folio_series_outside_the_narrow_band():
    """The folio shares the running-header line ~11-12% below the top."""
    pages = [obs(f"n{p}", p, (480, 94, 491, 104), str(p - 4), ocr=False) for p in (33, 34, 35)]
    lone = obs("x", 50, (480, 94, 491, 104), "7", ocr=False)
    body = obs("y", 36, (300, 400, 310, 410), "32", ocr=False)
    record = SimpleNamespace(observations=pages + [lone, body])
    assert folio_series_sources(record) == {"n33", "n34", "n35"}


def test_publication_version_seven_is_the_default():
    assert PublicationPolicy().version == "pdf-publication:7"
    with pytest.raises(ValueError):
        PublicationPolicy(version="pdf-publication:6")


def font(page=10, resource="/F31", name="LMMathSymbols8-Regular", differences=((48, "/prime"), (54, "/negationslash")), fingerprint="a" * 64):
    return PdfFontMetadata(
        page, resource, None, f"page:{page}:{resource}", "/XX+" + name, name, "/Type1", None, "available",
        "e" * 64, differences, (), "present_not_hashed", None, "missing", None, 0, (), fingerprint, "m", "not_applicable",
    )


def char(index, text, box, name):
    return PdfiumCharacter(10, index, text, box, name, "ok")


def word(source_id, start, text, box, page=10, width=595.0, height=842.0):
    location = DeepDocSourceLocation(page, width, height, DeepDocBoundingBox(*(v * (width if i % 2 == 0 else height) for i, v in enumerate(box))))
    return (source_id, start, start + len(text), text, location)


def block(text, page=10, number=3):
    return SimpleNamespace(page=page, block=number, source_id=f"pdf:text:{page}:{number}", text=text, bbox=(0, 0, 595, 842), page_width=595.0, page_height=842.0)


def test_tex_prime_is_recovered_only_where_the_font_names_it():
    """``y0(0)``: the first 0 is ``/prime`` of LMMathSymbols, the second a
    real zero of LMRoman. Only the prime is replaced."""
    text = "y0(0) = 5"
    chars = [
        char(0, "y", (0.10, 0.10, 0.11, 0.12), "LMMathItalic10-Regular"),
        char(1, "0", (0.111, 0.10, 0.115, 0.11), "LMMathSymbols8-Regular"),
        char(2, "(", (0.116, 0.10, 0.118, 0.12), "LMRoman10-Regular"),
        char(3, "0", (0.119, 0.10, 0.124, 0.12), "LMRoman10-Regular"),
        char(4, ")", (0.125, 0.10, 0.127, 0.12), "LMRoman10-Regular"),
    ]
    words = [word("pdf:text:10:3", 0, "y0(0)", (0.099, 0.099, 0.128, 0.121))]
    corrections, findings = propose_tex_glyph_corrections("c" * 64, [font()], {10: chars}, [block(text)], words)
    assert [f["code"] for f in findings] == ["PDF_TEX_GLYPH_NAME_RECOVERED"]
    (correction,) = corrections
    assert apply_verified_font_glyph_correction(text, pdf_sha256="c" * 64, page=10, block=3, correction=correction) == "y′(0) = 5"


def test_ambiguous_tex_glyph_is_reported_on_its_block_not_guessed():
    text = "h00 0"
    chars = [char(1, "0", (0.111, 0.10, 0.115, 0.11), "LMMathSymbols8-Regular")]
    # Poppler word text and PDFium characters disagree (one glyph, three 0s).
    words = [word("pdf:text:10:3", 0, "h00", (0.099, 0.099, 0.128, 0.121))]
    corrections, findings = propose_tex_glyph_corrections("c" * 64, [font()], {10: chars}, [block(text)], words)
    assert corrections == []
    assert [(f["code"], f["source_id"]) for f in findings] == [("PDF_TEX_GLYPH_NAME_UNRESOLVED", "pdf:text:10:3")]


def test_font_name_with_two_encodings_is_not_trusted():
    fonts = [font(), font(resource="/F40", differences=((48, "/zero"),), fingerprint="b" * 64)]
    chars = [char(1, "0", (0.111, 0.10, 0.115, 0.11), "LMMathSymbols8-Regular")]
    words = [word("pdf:text:10:3", 0, "h0", (0.099, 0.099, 0.128, 0.121))]
    assert propose_tex_glyph_corrections("c" * 64, fonts, {10: chars}, [block("h0")], words) == ([], [])


def test_glyph_name_proof_binds_the_table_value():
    good = dict(page=10, font_fingerprint="a" * 64, base_font="LMMathSymbols8-Regular", glyph_name="/prime", character_code_hex="30", extracted_text="0", replacement="′", glyph_bbox_normalized=(0.1, 0.1, 0.2, 0.2))
    assert DeepDocGlyphNameProof(**good).replacement == "′"
    for bad in ({"replacement": "'"}, {"character_code_hex": "31"}, {"glyph_name": "/zero"}):
        with pytest.raises(ValueError):
            DeepDocGlyphNameProof(**{**good, **bad})
    assert tex_glyph("/integraltext") == "∫" and tex_glyph("/parenleftbigg") == "(" and tex_glyph("/zero") is None


def box(key, x0, y0, x1, y1, order):
    return _Box(key, order, 100, x0, y0, x1, y1, 595.276, 841.89, "PARAGRAPH", "TEXT")


def exercise_page(extra=()):
    boxes = [box("head", 142, 174, 372, 184, 0)]
    for i in range(7):
        y = 195 + 24 * i
        boxes.append(box(f"L{i + 1}", 155, y, 250, y + 12, 1 + 2 * i))
        boxes.append(box(f"R{i + 8}", 343, y, 440, y + 12, 2 + 2 * i))
    boxes.append(box("tail", 142, 362, 352, 372, 30))
    return boxes + list(extra)


def test_layout_three_reads_exercise_columns_column_by_column():
    """ban_chinh_sua p.100: "Bài tập 10" spans the gutter of items 1-7 | 8-14."""
    order = [b.key for b in _page_flow(exercise_page(), PdfLayoutPolicy(version="pdf-layout:3"))[0]]
    assert order == ["head", *[f"L{i}" for i in range(1, 8)], *[f"R{i}" for i in range(8, 15)], "tail"]
    legacy = [b.key for b in _page_flow(exercise_page(), PdfLayoutPolicy(version="pdf-layout:2"))[0]]
    assert legacy[1:3] == ["L1", "R8"]


def test_layout_three_keeps_row_order_when_a_heading_sits_inside_a_column():
    """ban_chinh_sua p.44: Poppler merged the next heading with a formula, so
    it starts at the heading margin inside the left column."""
    stuck = box("stuck", 142, 280, 300, 300, 40)
    order = [b.key for b in _page_flow(exercise_page([stuck]), PdfLayoutPolicy(version="pdf-layout:3"))[0]]
    assert order[1:3] == ["L1", "R8"]
