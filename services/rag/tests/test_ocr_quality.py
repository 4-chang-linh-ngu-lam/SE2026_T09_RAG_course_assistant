"""LaTeX checks shared by model OCR, using recorded and synthetic output."""

import hashlib
import json
from pathlib import Path

import pytest
from idp.documents.paddle import _bbox_of, _block_type, _table_html
from idp.documents.preprocess import analyze_page, preprocess_image
from idp.ocr.backends.advanced import marker_blocks
from idp.ocr.backends.latex_check import check_latex
from idp.ocr.backends.scan import ScanGpuBackend
from idp.ocr.backends.scan_worker import formula_regions
from idp.ocr.fast import parse_hocr_lines
from idp.pdf.acquire import AcquisitionRequest
from idp.pdf.geometry import Affine
from idp.pdf.render import ImageFrame, TransformStep
from idp.structured.questions import analyze_questions
from idp.structured.structure import parse_table_html
from PIL import Image

RECORDED = Path(__file__).parent / "fixtures/recorded/formulanet-s-variance-loop.json"


def test_question_keeps_geometry_point_and_currency_options():
    text = "Câu 1. Xét góc tại A. A. $10 B. $20 C. $30 D. $40"
    page = {
        "page_id": 1,
        "blocks": [{"block_id": "q", "block_type": "Text", "text": text}],
    }
    group = analyze_questions([page])["groups"][0]
    assert group["stem"] == "Xét góc tại A."
    assert [(option["label"], option["text"]) for option in group["options"]] == [
        ("A", "$10"),
        ("B", "$20"),
        ("C", "$30"),
        ("D", "$40"),
    ]


def test_hocr_keeps_header_and_caption_as_separate_lines():
    def line(kind, text, y):
        return (
            f'<span class="ocr_{kind}" title="bbox 0 {y} 90 {y + 12}">'
            f'<span class="ocrx_word" title="bbox 1 {y} 70 {y + 12}; x_wconf 99">{text}</span>'
            "</span>"
        )

    hocr = (
        line("header", "Header", 0)
        + line("line", "Body", 20)
        + line("caption", "Caption", 40)
    )
    assert [item["text"] for item in parse_hocr_lines(hocr)] == [
        "Header",
        "Body",
        "Caption",
    ]


def test_preprocess_supports_vietnamese_paths(tmp_path):
    source = tmp_path / "ảnh gốc.png"
    target = tmp_path / "ảnh đã sửa.png"
    Image.new("RGB", (60, 40), "white").save(source)
    analysis = analyze_page(source)
    assert (analysis["width"], analysis["height"]) == (60, 40)
    assert preprocess_image(source, target, {}) == str(target)
    with Image.open(target) as result:
        assert result.size == (60, 40)


@pytest.mark.parametrize(
    "markup",
    [
        "<table><tr><th>Value</td></tr></table>",
        "<table><tr><td>Value</td></tr><td>Extra</td></table>",
        "<table><tr><td rowspan='2'>Value</td></tr></table>",
    ],
)
def test_table_html_checks_physical_rows_and_cell_tags(markup):
    with pytest.raises(ValueError):
        parse_table_html(markup)


def test_table_html_keeps_empty_last_row():
    result = parse_table_html("<table><tr><td>Value</td></tr><tr></tr></table>")
    assert result["rows"] == 2
    assert not result["rectangular"]


def test_marker_preserves_structured_parent_and_ignores_empty_page():
    page = {"block_type": "Page", "bbox": [0, 0, 10, 10]}
    assert marker_blocks({"children": [page]}) == ([], page["bbox"])
    table = {
        "block_type": "Table",
        "bbox": [1, 1, 9, 9],
        "html": "<table><tr><td>5</td></tr></table>",
        "children": [{"block_type": "Text", "html": "5"}],
    }
    assert marker_blocks({"children": [{**page, "children": [table]}]}) == (
        [table],
        page["bbox"],
    )


def test_paddle_preserves_caption_labels_polygon_geometry_and_math_escaping():
    assert _block_type("table_title") == _block_type("figure_title") == "Caption"
    assert _bbox_of([[2, 0], [4, 1], [3, 6], [1, 4]]) == [1, 0, 4, 6]
    assert (
        _table_html("| $x < 0$ |")
        == "<table><tr><td><math>x &lt; 0</math></td></tr></table>"
    )


def test_latex_check_flags_recorded_decoder_loop():
    # Real PP-FormulaNet_plus-S output for the SGK sample-variance crop.
    latex = json.loads(RECORDED.read_text(encoding="utf-8"))["rec_formula"]
    check = check_latex(latex)
    assert check["status"] == "review"
    assert "repetition" in check["reasons"]


@pytest.mark.parametrize(
    "latex,reasons",
    [
        # Real plus-S outputs measured on hand-labelled crops.
        (r"\Delta_{}}=19,5-9,5=10.", {"unbalanced_braces"}),
        (
            r" left\{\begin{cases}{x\geq0}\\ {y\geq0}\\ {x+y\leq150.}\\ \end{cases}\right.",
            {"unbalanced_left_right"},
        ),
        (r"a{}}{^}{=}b{}^^2+c{}^{2}-2b c\operatorname{c o s}A,", {"unbalanced_braces"}),
        (r"s^{2}=\frac{(x)}{n}{}^{n}{}^{n}{}^{n}{}^{n}{}^{n}", {"repetition"}),
        (r"\frac12", {"frac_without_group"}),
        ("", {"empty"}),
    ],
)
def test_latex_check_reasons(latex, reasons):
    check = check_latex(latex)
    assert check["status"] == "review" and reasons <= set(check["reasons"])


@pytest.mark.parametrize(
    "latex",
    [
        # Real plus-M outputs on the same crops (syntax fine; correctness is
        # a separate question answered only against ground truth).
        r"\begin{cases}x\geq0\\y\geq0\\x+y\leq150.\end{cases}",
        r"\hat{S}^{2}=\frac{\left(X_{1}-\overline{X}\right)^{2}+\left(X_{2}-\overline{X}\right)^{2}+\cdots+\left(X_{n}-\overline{X}\right)^{2}}{n-1},",
        r"\frac{a}{\sin A}=\frac{b}{\sin B}=\frac{c}{\sin C}=2R.",
        r"x=1000000000",
    ],
)
def test_latex_check_accepts_well_formed_output(latex):
    assert check_latex(latex) == {
        "version": "latex-check:2",
        "status": "syntax_ok",
        "reasons": [],
    }


def test_formula_regions_keep_different_crop_edges():
    first = {"bbox": [0, 0, 100, 20]}
    near = {"bbox": [1, 1, 101, 20]}
    short = {"bbox": [0, 0, 80, 20]}
    other = {"bbox": [200, 100, 230, 120]}
    grouped = formula_regions([first], [near, short, other])
    assert [[v["bbox"] for v in g["alternatives"]] for g in grouped] == [
        [first["bbox"], short["bbox"]],
        [other["bbox"]],
    ]


def test_scan_withholds_formulas_and_numeric_disagreements(tmp_path):
    image = b"test frame"
    sha = hashlib.sha256(image).hexdigest()
    frame = ImageFrame(
        sha,
        1,
        (100, 100, (0, 0, 100, 100), 0),
        "test",
        (TransformStep("render", Affine(), {}, (100, 100), sha),),
    )
    plan = AcquisitionRequest("test", frame)
    backend = ScanGpuBackend.__new__(ScanGpuBackend)
    backend.artifact_dir = tmp_path
    backend.config_sha256 = sha
    layout = {
        "weights": {},
        "formula_regions": [
            {
                "alternatives": [
                    {
                        "bbox": [0, 10, 15, 20],
                        "crop_bbox": [0, 8, 16, 22],
                        "detector": "yolov8-mfd",
                        "score": 0.9,
                        "latex": "x=1",
                    }
                ],
            }
        ],
    }
    baseline = [
        ("Phuong sai", [0, 0, 30, 9]),
        ("x=1", [0, 10, 30, 20]),
        ("12 7", [0, 30, 30, 40]),
        ("46-43=3", [0, 50, 20, 60]),
    ]
    book = {
        "words": [{"text": text, "bbox": box, "score": 0.9} for text, box in baseline],
        "excluded": [3],
        "regions": [{"bbox": [0, 45, 40, 65], "word_indices": [3]}],
    }
    easy = {
        "words": [
            {"text": text, "score": 0.9}
            for text in ("Phương sai", "x=1", "12 3 7", "46 = 43 = 3")
        ]
    }
    result = backend._assemble(image, sha, plan, layout, book, easy, None)
    assert [b.text for b in result.blocks] == ["Phương sai"]
    assert {d.code for d in result.diagnostics} == {
        "SCAN_FORMULA_UNVERIFIED",
        "SCAN_INLINE_MATH_REVIEW",
        "SCAN_NUMERIC_DISAGREEMENT",
        "SCAN_TABLE_REVIEW",
    }
    assert result.proposals[0]["latex"] == "x=1"
    assert result.proposals[1]["numeric_disagreement"] is True
    assert (tmp_path / result.proposals[0]["image_ref"]).read_bytes() == image
