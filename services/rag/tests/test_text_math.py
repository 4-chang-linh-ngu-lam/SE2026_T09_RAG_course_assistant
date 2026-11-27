"""Text-layer math rebuild: geometry -> scripts/fractions, lossless or nothing."""

from idp.processing.formula import Glyph, rebuild, reconstruct_page_math
from rag.search.retrieval_plan import _flatten_latex, terms

MAIN, SCRIPT = 10.9, 7.97


def g(c, x, baseline, size=MAIN, font="LMMathItalic10", width=5.0):
    top = baseline - 0.75 * size
    return Glyph(c, x, top, x + width, baseline + 0.25 * size, baseline, size, font)


def test_scripts_from_size_and_baseline():
    # N_0 e^{-kt}: subscript is lower and smaller, exponent higher and smaller.
    glyphs = [
        g("N", 0, 283.3), g("0", 6, 284.9, SCRIPT), g("e", 11, 283.3),
        g("−", 16, 278.8, SCRIPT), g("k", 20, 278.8, SCRIPT), g("t", 24, 278.8, SCRIPT),
    ]
    result = rebuild(glyphs, [])
    assert result.text == "N_{0}e^{−kt}"
    assert result.structured and not result.issues


def test_prime_is_not_an_exponent_and_space_glyph_is_not_a_line():
    glyphs = [
        g("N", 0, 100), g("′", 6, 96, SCRIPT), g("(", 9, 100), g("t", 13, 100),
        g(")", 18, 100), g(" ", 23, 96, MAIN), g("=", 27, 100),
    ]
    assert rebuild(glyphs, []).text == "N′(t) ="


def test_fraction_from_rule_and_neighbouring_text_line_is_not_absorbed():
    glyphs = [
        g("b", 0, 311.6, font="LMRoman10"), g("á", 6, 311.6, font="LMRoman10"),
        g("T", 0, 329.6), g("=", 8, 329.6, font="LMRoman10"),
        g("l", 20, 322.3, font="LMRoman10", width=3), g("n", 23, 322.3, font="LMRoman10"),
        g(" ", 28, 322.3, font="LMRoman10", width=2), g("2", 30, 322.3, font="LMRoman10"),
        g("k", 24, 337.1),
    ]
    result = rebuild(glyphs, [(19.0, 36.0, 326.9)])
    assert result.text == "bá\nT = \\frac{ln 2}{k}"


def test_omx_codes_map_sized_delimiters_and_keep_extensible_pieces_out():
    ext = "LMMathExtension10"
    paren = [g("F", 0, 100), g("\x12", 6, 92, 9.96, ext), g("x", 12, 100), g("\x13", 18, 92, 9.96, ext)]
    assert rebuild(paren, []).text == "F(x)"
    piece = [g("x", 0, 100), g("\x0c", 6, 92, 9.96, ext)]
    assert "extension_glyph" in rebuild(piece, []).issues


def test_integral_in_exponent_and_sum_limits():
    ext = "LMMathExtension10"
    # e^{∫p dx}: the text-style integral's origin sits 0.82em above the
    # exponent baseline it is set on.
    exponent = 325.6
    glyphs = [
        g("e", 0, 330.3),
        g("R", 6, exponent - 0.82 * 9.96, 9.96, ext),
        g("p", 11, exponent, SCRIPT), g("d", 15, exponent, SCRIPT), g("x", 19, exponent, SCRIPT),
    ]
    assert rebuild(glyphs, []).text == "e^{∫pdx}"
    # A display sum keeps its limits even when they are wider than it.
    sigma = Glyph("X", 10, 90, 22, 112, 92, 9.96, ext)
    limits = [g("i", 8, 118, SCRIPT, width=3), g("=", 12, 118, SCRIPT), g("1", 17, 118, SCRIPT, width=3),
              g("n", 13, 86, SCRIPT, width=3)]
    text = rebuild([g("y", 0, 100), sigma, *limits, g("α", 26, 100)], []).text
    assert text == "y ∑_{i=1}^{n} α"
    assert "operator_limits_missing" in rebuild([g("y", 0, 100), sigma, g("α", 26, 100)], []).issues


def test_unpaired_delimiters_reject_a_cut_region():
    assert "unbalanced" in rebuild([g("(", 0, 100), g("x", 5, 100)], []).issues


class FakePage:
    """Minimal pymupdf page: one rawdict span per glyph, no drawings."""

    def __init__(self, glyphs):
        self.glyphs = glyphs

    def get_text(self, kind, clip=None):
        spans = [{
            "font": x.font, "size": x.size,
            "chars": [{"c": x.c, "bbox": (x.x0, x.y0, x.x1, x.y1), "origin": (x.x0, x.baseline)}],
        } for x in self.glyphs]
        return {"blocks": [{"lines": [{"spans": spans}]}]}

    def get_drawings(self):
        return []


def _block(block_id, bbox, text, flags=()):
    return {"block_id": block_id, "block_type": "Text", "bbox": list(bbox), "text": text,
            "markdown": text, "review_flags": [{"code": c, "severity": "warning"} for c in flags]}


def test_page_rebuild_merges_pieces_and_publishes_latex_only_when_lossless():
    glyphs = [
        g("N", 0, 100), g("0", 6, 101.6, SCRIPT), g("e", 11, 100),
        g("k", 16, 95.5, SCRIPT), g("t", 20, 95.5, SCRIPT),
        g("=", 30, 100), g("1", 40, 100),
    ]
    page = FakePage(glyphs)
    blocks = [
        _block("b0", (0, 90, 25, 103), "N0ekt", ["FORMULA_TEXT_LAYER_FRAGMENT"]),
        _block("b1", (28, 90, 46, 103), "= 1", ["FORMULA_TEXT_LAYER_FRAGMENT"]),
    ]
    (merged,) = reconstruct_page_math(blocks, page)
    assert merged["block_type"] == "Equation"
    assert merged["text"] == "N_{0}e^{kt} = 1"
    assert merged["latex"] == ["N_{0}e^{kt} = 1"] and merged["latex_validation"][0]["valid"]
    assert merged["markdown"].startswith("$$")
    (flag,) = merged["review_flags"]
    assert flag["code"] == "FORMULA_TEXT_LAYER_RECONSTRUCTED" and flag["severity"] == "info"
    assert flag["merged_blocks"] == ["b0", "b1"]

    # A glyph the source blocks do not hold (or vice versa) keeps them as-is.
    lossy = [_block("b0", (0, 90, 25, 103), "N0ekt?", ["FORMULA_TEXT_LAYER_FRAGMENT"]),
             _block("b1", (28, 90, 46, 103), "= 1", ["FORMULA_TEXT_LAYER_FRAGMENT"])]
    assert reconstruct_page_math(lossy, page) == lossy

    # A piece that is still incomplete ("N_0 e^{kt} =") stays flagged.
    piece = [_block("b0", (0, 90, 33, 103), "N0ekt=", ["FORMULA_TEXT_LAYER_FRAGMENT"])]
    assert reconstruct_page_math(piece, FakePage(glyphs[:6])) == piece


def test_search_terms_flatten_rebuilt_math():
    assert _flatten_latex("y_{1}(x)") == "y1(x)"
    assert terms("ay_{1}(x) − by_{1}(x)y_{2}(x)") == terms("ay1(x) − by1(x)y2(x)")
    assert "y1" in terms("Gọi y_{1}(x) và y_{2}(x)")
    assert terms("T = \\frac{ln 2}{k}") == terms("T = ln 2 k")
    assert terms("Prose with no math.") == ["prose", "with", "no", "math"]


def test_ocr_input_is_grayscale_and_only_trusted_dpi_is_passed(tmp_path):
    from PIL import Image

    from idp.backends.text_ocr import _prepare

    source, target = tmp_path / "page.png", tmp_path / "staged.png"
    Image.new("RGB", (40, 20), (200, 180, 160)).save(source, dpi=(300, 300))
    assert _prepare(source, target) == 300
    with Image.open(target) as staged:
        assert staged.mode == "L" and staged.size == (40, 20)
    # 72/96 are unset defaults on uploads: not passed to Tesseract.
    for unset in (72, 96):
        Image.new("RGB", (40, 20)).save(source, dpi=(unset, unset))
        assert _prepare(source, target) is None
    Image.new("RGB", (40, 20)).save(source)
    assert _prepare(source, target) is None


def test_dual_read_marks_agreement_and_keeps_source_text(tmp_path):
    from PIL import Image

    from idp.evidence.cross_read import comparable_words, dual_read_page

    image = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(image)
    readings = iter(["Mệnh đề “P” đúng.", "KÉO THEO", RuntimeError("server down")])

    class Reader:
        identity = {"name": "fake"}

        def __call__(self, crop):
            value = next(readings)
            if isinstance(value, Exception):
                raise value
            return value

    def line(block_id, text, y):
        return {"block_id": block_id, "block_type": "Text", "source": "tesseract_fallback",
                "bbox": [10, y, 90, y + 10], "text": text, "review_flags": []}

    page = {"page_size": [100, 50], "blocks": [
        line("b0", "mệnh đề P đúng", 0), line("b1", "KÉO THE0", 15), line("b2", "x", 30),
        {"block_id": "b3", "block_type": "Equation", "source": "tesseract_fallback",
         "bbox": [0, 40, 10, 49], "text": "x", "review_flags": []},
    ]}
    summary = dual_read_page(page, image, Reader())
    assert (summary["agreed"], summary["disagreed"], summary["failed"]) == (1, 1, 1)
    flags = {b["block_id"]: [f["code"] for f in b["review_flags"]] for b in page["blocks"]}
    assert flags == {"b0": ["OCR_DUAL_READ_AGREED"], "b1": ["OCR_DUAL_READ_DISAGREE"],
                     "b2": ["OCR_DUAL_READ_FAILED"], "b3": []}
    assert page["blocks"][1]["text"] == "KÉO THE0"  # never replaced
    assert page["blocks"][1]["review_flags"][0]["alternative"] == "KÉO THEO"
    assert comparable_words(r"\(AB^{2}\) = 9,5") == comparable_words("AB^2 = 9.5")
