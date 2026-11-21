"""Regression tests for the 2026-11-19 IDP bug audit (filtering, quality
gates, native/digital parsing). Each test names the audited behaviour."""

import io
import json
import math
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

FIX = Path(__file__).parent / "fixtures/generated"


# --- input/filetypes.py -----------------------------------------------------

def test_html_renamed_to_pdf_is_rejected(tmp_path):
    from idp.input.filetypes import InputError, detect_file_type

    path = tmp_path / "page.pdf"
    path.write_text("<!doctype html><html><body>hi</body></html>", encoding="utf-8")
    with pytest.raises(InputError) as error:
        detect_file_type(path)
    assert error.value.code == "CORRUPT_FILE"


def test_pdf_opened_as_pdf_only(tmp_path):
    from idp.input.filetypes import InputError, validate_input

    png = tmp_path / "x.png"
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0).save(png)
    with pytest.raises(InputError):
        validate_input(png, "pdf")


def test_pdf_header_after_leading_bytes_and_riff_audio(tmp_path):
    from idp.input.filetypes import InputError, detect_file_type

    doc = fitz.open()
    doc.new_page()
    shifted = tmp_path / "shifted.pdf"
    shifted.write_bytes(b"\n" * 100 + doc.tobytes())
    assert detect_file_type(shifted) == "pdf"
    wav = tmp_path / "sound.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32)
    with pytest.raises(InputError):
        detect_file_type(wav)


# --- pdf/native/preflight.py ------------------------------------------------

def _dag_pdf(depth):
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"]
    for level in range(depth):
        number = 3 + level
        objects.append(f"<< /Type /Pages /Kids [{number + 1} 0 R {number + 1} 0 R] /Count 1 >>")
    objects.append("<< /Type /Page /MediaBox [0 0 100 100] >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def test_page_tree_dag_is_rejected_before_flattening():
    from idp.pdf.native.preflight import PdfAdmissionError, PdfAdmissionPolicy, PdfSource

    with pytest.raises(PdfAdmissionError) as error:
        PdfSource(_dag_pdf(22), PdfAdmissionPolicy(max_pages=5))
    assert error.value.diagnostic.code in {"PDF_PAGE_TREE_INVALID", "PDF_PAGE_LIMIT"}


# --- resource limits --------------------------------------------------------

def test_ledger_rejects_non_integer_reservations():
    from idp.pdf.resource import ResourceLedger

    from time import monotonic

    ledger = ResourceLedger(monotonic() + 60, max_calls=5, max_pixels=100, max_regions=5)
    for value in (float("nan"), 1.5, True):
        with pytest.raises(ValueError):
            ledger.reserve(f"k{value}", pixels=value)
    ledger.reserve("ok", pixels=50)
    assert ledger.pixels == 50


def test_job_limits_cannot_raise_admission_caps():
    from idp.runtime.lanes import configuration

    with pytest.raises(ValueError):
        configuration(limits=["max_pages"])
    with pytest.raises(ValueError):
        configuration(limits={"max_pages": 10**9})
    assert configuration(limits={"max_pages": 10}).admission.max_pages == 10


# --- pdf/native/quality.py --------------------------------------------------

def _gate(findings, proofs):
    from idp.pdf.native.quality import PdfQualityPolicy, assess_candidate

    evidence = SimpleNamespace(
        id="evidence:1", glyph_proofs=proofs, review=None, asset_ids=(),
        independence_family="poppler", origin=None, producer=SimpleNamespace(name="poppler-pdftotext"),
    )
    region = SimpleNamespace(id="region:1", labels=(SimpleNamespace(value="TEXT"),), source_id="pdf:text:1:0")
    trace = SimpleNamespace(evidence=(evidence,), region=region, figure=None, source_candidate_id="candidate:1")
    candidate = SimpleNamespace(
        id="candidate:1", evidence_ids=("evidence:1",), origin=None, figure=None, table=None, formula=None, text="a ≠ b",
    )
    return assess_candidate(trace, candidate, findings, policy=PdfQualityPolicy("pdf-quality-gate:3"))


def _finding(code, status="SUSPECT", **extra):
    return SimpleNamespace(code=code, status=status, character_code_hex=extra.get("hex"), glyph_name=extra.get("glyph"))


def test_glyph_proof_does_not_hide_other_findings():
    proof = SimpleNamespace(character_code_hex="36", glyph_name="/negationslash")
    resolved = _gate([_finding("PDF_FONT_GLYPH_MAPPING_SUSPECT", hex="36")], (proof,))
    assert resolved.action.value == "ACCEPT"
    for other in ("PDF_TEXT_CID_PLACEHOLDER", "PDF_SECONDARY_TEXT_UNASSIGNED", "PDF_FONT_INSPECTION_UNAVAILABLE"):
        blocked = _gate([_finding("PDF_FONT_GLYPH_MAPPING_SUSPECT", hex="36"), _finding(other)], (proof,))
        assert blocked.action.value == "VERIFY", other
    conflict = _gate([_finding("PDF_FONT_GLYPH_RECOVERY_CONFLICT", "CONFLICT", hex="36")], (proof,))
    assert conflict.action.value == "VERIFY"


# --- pdf/native/scoping.py --------------------------------------------------

def test_scoping_never_narrows_conflicts_and_uses_glyph_name_form():
    from idp.pdf.native.scoping import finding_targets

    base = dict(scope="FONT_RESOURCE", source_id=None, page=1, operator_index=None, string_index=None,
                code_index=None, resource_scope=None, raw_extracted_text=None, unicode_mapping=None,
                character_code_hex=None, glyph_name=None)
    conflict = SimpleNamespace(id="a", code="PDF_FONT_GLYPH_MAPPING_SUSPECT", status="CONFLICT", **{**base, "unicode_mapping": "x"})
    named = SimpleNamespace(id="b", code="PDF_FONT_GLYPH_MAPPING_SUSPECT", status="SUSPECT", **{**base, "glyph_name": "/minus"})
    texts = {1: [("pdf:text:1:0", "x and y"), ("pdf:text:1:1", "a − b")]}
    targets = finding_targets([conflict, named], texts)
    assert targets["a"] is None
    assert targets["b"] == frozenset({"pdf:text:1:1"})


# --- LaTeX validation / normalization ---------------------------------------

@pytest.mark.parametrize("latex", [
    r"x \rightarrow y", r"A \leftarrow B \leftrightarrow C", r"\left\{ \begin{array}{l} x \\ y \end{array} \right.",
    r"x \in [0; \pi/2)", r"\text{nếu (a) đúng}", r"\{1, 2\}",
])
def test_validate_latex_accepts(latex):
    from idp.validation.validate import validate_latex

    assert validate_latex(latex).valid


@pytest.mark.parametrize("latex", [
    r"([)]", r"\begin{cases} x \end{matrix}", r"\right) x \left(", r"(x \; y]", r"\text{a{b}",
])
def test_validate_latex_rejects(latex):
    from idp.validation.validate import validate_latex

    assert not validate_latex(latex).valid


def test_incomplete_formula_is_checked_per_formula():
    from idp.validation.validate import incomplete_formula_reasons

    assert incomplete_formula_reasons([r"\lim_{x \to 0^+} f(x)"]) == []
    assert "dangling operator" in incomplete_formula_reasons([r"x = ", "y = 2"])
    assert "empty argument" in incomplete_formula_reasons([r"\frac{a}{}"])
    assert "empty argument" in incomplete_formula_reasons([r"\sqrt[3]{}"])


def test_latex_check_frac_and_order():
    from idp.ocr.backends.latex_check import check_latex

    assert "frac_without_group" in check_latex(r"\frac{a+b}")["reasons"]
    assert "unbalanced_environment" in check_latex(r"\begin{a}\begin{b}\end{a}\end{b}")["reasons"]
    assert check_latex(r"x \\ \begin{array}{c} 1 \end{array}")["status"] == "syntax_ok"


def test_normalize_latex_keeps_arrows_and_dollars():
    from idp.documents.normalize import normalize_latex

    assert normalize_latex(r"x \rightarrow y") == r"x \rightarrow y"
    assert normalize_latex(r"\leftrightarrow") == r"\leftrightarrow"
    assert normalize_latex(r"\left( a \right)") == "( a )"
    assert normalize_latex("\\$50") == "\\$50"
    assert normalize_latex("$x$") == "x"


# --- canonical audit ----------------------------------------------------------

def _doc(blocks, review=(), status="ok"):
    return {
        "pages": [{"page_id": 1, "status": status, "page_size": [100, 100], "blocks": blocks, "review": list(review)}],
        "expected_pages": [1], "parser": {"name": "pymupdf"},
    }


def _block(**extra):
    return {"block_id": "b1", "type": "Text", "bbox": [1, 1, 50, 20], "source": "pymupdf", "text": "Hello world", **extra}


def test_audit_gaps_are_closed():
    from idp.canonical import audit_canonical

    trusted = {"pymupdf"}
    empty = _block(text="", review_flags=[{"code": "EMPTY_BLOCK_LOW_CONFIDENCE", "severity": "info"}])
    assert audit_canonical(_doc([empty]), trusted)["quality"]["page_quality"][0]["auto_publish"] is False
    invalid = _block(latex_validation=[{"valid": False}], review_flags=[{"code": "LOW_CONFIDENCE", "severity": "warning"}])
    assert audit_canonical(_doc([invalid]), trusted)["checks"]["formulas_valid_or_flagged"]["pass"] is False
    nan = _block(confidence=float("nan"))
    assert audit_canonical(_doc([nan]), trusted)["checks"]["low_confidence_flagged"]["pass"] is False
    garbled = audit_canonical(_doc([_block()], [{"code": "PAGE_TEXT_GARBLED", "severity": "error"}]), trusted)
    assert garbled["quality_pass"] is False and garbled["quality_certified"] is False
    blank = audit_canonical(_doc([], [{"code": "PAGE_OCR_EMPTY", "severity": "warning"}], status="blank"), trusted)
    assert blank["production_pass"] is False


def test_ingestion_check_requires_pass_true(tmp_path):
    from idp.validation.ingestion_checks import check_ingestion_artifacts

    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p0001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "canonical.json").write_text(json.dumps({"schema_version": 1, "source_sha256": "a", "pages": [{"page_id": 1}]}), encoding="utf-8")
    (tmp_path / "report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ingestion_report.json").write_text(json.dumps({"pass": False, "checks": {"blocks_valid": {"pass": False}}}), encoding="utf-8")
    result = check_ingestion_artifacts(tmp_path, [1])
    assert result["pass"] is False and "blocks_valid" in result["errors"][0]


# --- OCR fallback ---------------------------------------------------------------

def test_crop_orientation_returns_declared_order(monkeypatch, tmp_path):
    from PIL import Image

    from idp.ocr import fallback

    monkeypatch.setattr(fallback, "_read_crop", lambda *args, **kwargs: ("recovered text", 0.91))
    text, confidence, angle = fallback.crop_text_with_orientation(Image.new("RGB", (60, 20), "white"), tmp_path, "c")
    assert (text, confidence, angle) == ("recovered text", 0.91, 0)


# --- text-layer filters -------------------------------------------------------

def test_url_noise_is_a_share_not_a_length():
    from idp.pdf.profiling import _url_noise

    assert _url_noise("TOÁN") is False
    assert _url_noise("100%") is False
    assert _url_noise("https://toanmath.com " * 50 + "Trang") is True


def test_text_quality_filters():
    from idp.documents.text_quality import is_garbled_text, needs_ocr, repeated_watermark_tokens

    for noise in ("...", "---", "5", "." * 45):
        assert needs_ocr(noise)[0]
    assert needs_ocr("WWW.TOANMATH.COM www.toanmath.com")[1] == "repeated_url_only_text_layer"
    assert needs_ocr("Bài học hôm nay rất hay và có nhiều ví dụ minh họa cụ thể.") == (False, None)
    assert not is_garbled_text(" item one\n item two")
    assert is_garbled_text("clean text " * 50 + "\n\x01\x02\x03\x04")
    assert repeated_watermark_tokens(["A"] * 4 + ["0"] * 4 + ["DRAFT", "draft", "Draft", "DRAFT"]) == ["draft"]


# --- publication -------------------------------------------------------------

def test_folio_value_keeps_content_numbers():
    from idp.pdf.publication import folio_value

    assert folio_value("12") == 12 and folio_value("- 12 -") == 12
    for content in ("-12", "1.2", "$12", "100%", "19/11", "-5 + 3"):
        assert folio_value(content) is None


def test_v2_decides_native_before_ocr():
    from idp.publish import decision_order

    blocks = [{"origin": "OCR", "id": 1}, {"origin": "NATIVE", "id": 2}, {"origin": "OCR", "id": 3}]
    assert [b["id"] for b in decision_order(blocks)] == [2, 1, 3]


# --- geometry -------------------------------------------------------------------

def test_inverted_boxes_and_bleed_glyphs():
    from idp.pdf.native.geometry import page_geometry, to_display_bbox

    page = SimpleNamespace(mediabox=(200, 400, 0, 0), cropbox=(200, 400, 0, 0), get=lambda key, default=None: default)
    geometry = page_geometry(page, 1)
    assert (geometry.width, geometry.height) == (200, 400)
    assert to_display_bbox((-3, 10, -0.5, 20), geometry) == (None, "outside_visible_page")


def test_exception_message_is_diagnostic_safe():
    from idp.evidence.contracts import DeepDocDiagnostic
    from idp.pdf.native.contracts import exception_message

    for exc in (ValueError(), ValueError("trailing  "), RuntimeError("x" * 5000)):
        DeepDocDiagnostic("CODE", exception_message(exc))
    assert exception_message(ValueError("kept as is")) == "kept as is"


def test_cmap_spaced_hex_and_mismatched_cid_range():
    from idp.pdf.native.glyph.inspector import _parse_cid_encoding_cmap, _parse_tounicode

    cmap = _parse_tounicode(b"1 beginbfchar <00 41> <00 42> endbfchar")
    assert cmap.mappings[b"\x00A"] == "B"

    class Encoding(dict):
        def get_data(self):
            return b"begincidrange <00> <FFFF> 1 endcidrange begincidchar <00 41> 5 endcidchar"

    assert _parse_cid_encoding_cmap(Encoding()) == {b"\x00A": 5}


def test_pdfium_surrogate_pairs_are_one_character():
    from idp.pdf.native.glyph.backend import _character_text

    units = ["\ud835", "\udc65", "a"]

    class Page:
        def get_text_range(self, index, count, errors="strict"):
            return units[index]

    assert _character_text(Page(), 0, 3) == ("\U0001d465", 1)
    assert _character_text(Page(), 2, 3) == ("a", None)
    assert _character_text(Page(), 1, 3) == ("�", None)


# --- legacy validation helpers ------------------------------------------------

def test_split_formula_respects_environments():
    from idp.validation.repair import _split_formula

    assert _split_formula(r"x>0 \text{và} y<1") == ["x>0", "y<1"]
    assert _split_formula(r"\begin{cases} x \text{và} y \end{cases} \text{nên} z") == [
        r"\begin{cases} x \text{và} y \end{cases}", "z",
    ]


def test_corrections_keep_flags_and_never_collide_on_none(tmp_path):
    from idp.validation.corrections import apply_corrections

    page = {"blocks": [
        {"block_id": None, "order": None, "text": "a", "review_flags": []},
        {"block_id": "b2", "order": 2, "text": "b", "review_flags": [{"code": "LOW_CONFIDENCE", "severity": "warning"}]},
    ]}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(page), encoding="utf-8")
    applied = apply_corrections(path, [{"block_id": None, "text": "x"}, {"block_id": "b2", "latex": ["("]}])
    assert applied == ["b2"]
    codes = {f["code"] for f in json.loads(path.read_text(encoding="utf-8"))["blocks"][1]["review_flags"]}
    assert {"LOW_CONFIDENCE", "LATEX_INVALID", "HUMAN_CORRECTED"} <= codes


def test_strip_html_keeps_comparisons():
    from idp.documents.digital import _strip_html

    assert _strip_html("| x < 0 | x > 0 |") == "| x < 0 | x > 0 |"
    assert _strip_html("<td>a</td><!-- c --><br/>b") == "a b"


def test_preflight_text_ignores_watermarks_and_damage():
    from idp.input.preflight import _usable_text

    assert _usable_text("https://toanmath.com https://toanmath.com (cid:12)�").strip() == ""


def test_rotated_digital_boxes_are_in_display_frame(tmp_path):
    from idp.documents.digital import process

    result = process(FIX / "rotated_cropbox.pdf", tmp_path, ocr_fallback=False)
    canonical = json.loads((tmp_path / "canonical.json").read_text(encoding="utf-8"))
    page = canonical["pages"][0]
    width, height = page["page_size"]
    for block in page["blocks"]:
        x0, y0, x1, y1 = block["bbox"]
        assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
    assert result["pages"] == 1
    assert math.isclose(width, 560) and math.isclose(height, 360)
