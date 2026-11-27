"""PaddleOCR-VL primary reader: scores, confirmation, repair rules, page rewrite."""

from PIL import Image

from idp.ocr.vl_primary import (
    LOW, line_confidence, repair_line, split_lines, vl_reread_page, word_probs,
)


def tok(text, prob=0.99, alts=()):
    return (text, prob, list(alts))


def test_word_probs_ignore_markup_and_join_scripts():
    words = word_probs([tok("Ta có "), tok("\\("), tok("x"), tok("_{"), tok("1", 0.4), tok("}"),
                        tok(" \\frac", 0.2), tok("\\)")])
    assert words == [("ta", 0.99), ("có", 0.99), ("x1", 0.4)]


def test_repair_changes_only_marks_of_one_word_with_tesseract_support():
    tess = {"tứ", "giác", "số", "do"}
    fixed, repairs = repair_line([tok("tứ"[0]), tok("ư", 0.3, [("ứ", 0.6)]), tok(" giác")], tess)
    assert "".join(t[0] for t in fixed) == "tứ giác"
    assert repairs == [{"from": "tư", "to": "tứ", "probability": 0.3}]
    # A different letter/digit is never taken from a region-wide match.
    fixed, repairs = repair_line([tok("2"), tok("4", 0.3, [("3", 0.6)]), tok("0")], {"340"})
    assert repairs == [] and "".join(t[0] for t in fixed) == "240"
    # Tesseract's "d" is no evidence against VL's "đ".
    fixed, repairs = repair_line([tok("số "), tok("đo", 0.3, [("do", 0.6)])], tess)
    assert repairs == []
    # A word Tesseract already supports is left alone.
    _, repairs = repair_line([tok("tứ", 0.3, [("tư", 0.6)])], {"tứ", "tư"})
    assert repairs == []


def test_line_confidence_uses_unconfirmed_words_and_formula_agreement():
    line = [tok("Nửa", 0.4), tok(" số liệu")]
    assert line_confidence(line, "Text", "", set()) == 0.4
    assert line_confidence(line, "Text", "Nửa số liệu", {"nửa", "số", "liệu"}) == 1.0
    formula = [tok("a"), tok("^{"), tok("2", 0.5), tok("}"), tok("="), tok("b"), tok("^{"), tok("2", 0.5), tok("}"),
               tok("+"), tok("c"), tok("^{"), tok("2", 0.5), tok("}"), tok("-"), tok("2"), tok("bc"),
               tok("\\cos", 0.9), tok(" A")]
    # Tesseract garbles the exponents but agrees with the formula's skeleton.
    assert line_confidence(formula, "Equation", "a’ = b* +c? -2bccosA,", set()) == 1.0
    assert line_confidence(formula, "Equation", "", set()) == 0.5


def test_split_lines_keeps_alternatives():
    lines = split_lines([tok("Dòng một\nDòng", 0.9), tok(" hai", 0.8, [(" hải", 0.1)])])
    assert ["".join(t[0] for t in line) for line in lines] == ["Dòng một", "Dòng hai"]
    assert lines[1][1][2] == [(" hải", 0.1)]


class FakeReader:
    identity = {"name": "fake-vl"}

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def __call__(self, image, kind):
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _page(blocks, size=(400, 300)):
    return {"page_id": 7, "page_size": list(size), "blocks": blocks,
            "review": [{"code": "STRUCTURED_BUDGET_EXHAUSTED", "severity": "warning", "block_id": None},
                       {"code": "FAST_OCR_REVIEW", "severity": "warning", "block_id": None}]}


def _line(block_id, y, text, block_type="Text"):
    return {"block_id": block_id, "block_type": block_type, "bbox": [20, y, 380, y + 20], "text": text,
            "source": "tesseract_fast", "confidence": 0.9, "review_flags": []}


def test_reread_page_replaces_text_keeps_tables_and_flags_low_scores(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (800, 600), "white").save(image)
    table = {"block_id": "t", "block_type": "Table", "bbox": [20, 200, 380, 280], "text": "", "review_flags": []}
    # Tesseract misread "hai", so VL's doubtful "hai" has no confirmation.
    page = _page([_line("a", 10, "Nửa số liệu"), _line("b", 35, "dòng hal"), table,
                  _line("c", 210, "ô bảng"), {"block_id": "p", "block_type": "Picture", "bbox": [0, 150, 50, 190]}])
    reader = FakeReader([[tok("Nửa số liệu\n"), tok("dòng"), tok(" ha", 0.2), tok("i", 0.99)]])
    summary = vl_reread_page(page, image, reader)
    assert (summary["lines"], summary["low_confidence"]) == (2, 1)
    texts = {b["block_id"]: b for b in page["blocks"]}
    vl = [b for b in page["blocks"] if b.get("source") == "paddleocr_vl_gguf"]
    assert [b["text"] for b in vl] == ["Nửa số liệu", "dòng hai"]
    assert vl[0]["bbox"] == [20, 10, 380, 30] and vl[1]["bbox"] == [20, 35, 380, 55]
    assert vl[1]["confidence"] < LOW and "LOW_CONFIDENCE" in {f["code"] for f in vl[1]["review_flags"]}
    # The table and its lines, and non-text blocks, stay as they were.
    assert {"t", "c", "p"} <= set(texts) and "a" not in texts and "b" not in texts
    # The formula-budget note is superseded; other page notes stay.
    assert [f["code"] for f in page["review"]] == ["FAST_OCR_REVIEW"]


def test_reread_page_keeps_tesseract_where_the_reader_fails(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 300), "white").save(image)
    far = _line("z", 200, "xa")
    page = _page([_line("a", 10, "một"), far])
    reader = FakeReader([[tok("một")], RuntimeError("server down")])
    summary = vl_reread_page(page, image, reader)
    assert summary["failed"] == 1
    assert {b["block_id"] for b in page["blocks"]} >= {"z"}


class SlowKeyedReader:
    """Answers by crop height (one distinct height per region), out of order."""

    def __init__(self, parallel):
        self.parallel = parallel

    def __call__(self, image, kind):
        import time
        time.sleep(0.05 if image.height < 60 else 0.0)
        return [tok(f"vùng {image.height}")]


def test_parallel_region_reads_keep_region_order(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 300), "white").save(image)

    def run(parallel):
        page = _page([_line("a", 10, "vùng"), {**_line("b", 120, "vùng"), "bbox": [20, 120, 380, 170]},
                      {**_line("c", 230, "vùng"), "bbox": [20, 230, 380, 290]}])
        vl_reread_page(page, image, SlowKeyedReader(parallel))
        return [(b["block_id"], b["text"]) for b in page["blocks"]]

    assert run(4) == run(1)
