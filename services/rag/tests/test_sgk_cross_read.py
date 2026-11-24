"""SGK scan: formula/table cross-reads, verification tiers, section headings."""

import pytest

from idp.canonical import audit_canonical, build_canonical, cross_check_structured
from idp.structured.cross_read import formula_agreement, table_agreement
from idp.structured.questions import analyze_questions, numbered_heading, textbook_boundary
from rag.retrieval.canonical_harness import build_chunks, iter_retrievable_blocks

SHA = "e" * 64

# Real SGK Toán 10 pairs: (formula model LaTeX, Tesseract line it sits on).
AGREE = [
    ("3x^{2}-5x+2=0", "a) Phương trình 3x” - 5x +2 =0 có nghiệm nguyên;"),
    ("AB^{2}+AC^{2}=BC^{2}", "Q: “Tam giác ABC có AB” + AC? = BC””."),
    ("P\\Rightarrow Q.", "kí hiệu là P= Q."),
    ("Q:\\exists x\\in\\mathbb{Q},x^2=2.", "Q: “3x 6Q, x* =2”."),
    ("\\mathbb{N}\\subset\\mathbb{Z}\\subset\\mathbb{Q}\\subset\\mathbb{R}.",
     "Mối quan hệ giữa các tập hợp số: Nc Z c @ c IR."),
    ("a^{2}=b^{2}+c^{2}-2bc\\cos A", "a’ = b* +c? -2bccosA,"),
    ("Q_{1}=(8+11):2=9.5.", "Do đó, Q,= (8 + 11) :2 = 9,5."),
]
REJECT = [
    # Hallucinations over prose or quotes.
    ("\\dot{\\theta}=5", "+ Với n= 5 ta được mệnh đề “5 chia hét cho 2”."),
    ("0^{\\circ}", "cộng với 1 bằng 0”."),
    ("\\vec{110}^{ 甲 }", "Mệnh đề “Có một số tự nhiên nhân với 1 không bằng chính nó”"),
    # A Greek letter the OCR line does not show ("2ca" printed).
    ("b^{2}=c^{2}+a^{2}-2c\\alpha\\cos B,", "b* =cˆ+a” -2cacosB,"),
    # Truncated set: the closing brace is required.
    ("D=\\{7\\}", "a) D= {7; 11; 13; 17; 19}. Tập hợp D có 5 phan tử."),
    # A superscript the OCR shows no trace of.
    ("2^{2}x+y\\leq0;", "a)2x+3y>6, bì 2x+y<0;"),
    # "và" read as \forall / trailing V of "và".
    ("b=8,c=5\\forall\\widehat{B}=80^{\\circ}", "Cho tam giác ABC có b= 8, c=5 và B =80°."),
    ("7x+4y\\leq2400V", "bat phương trình 7x + 4y <2 400 và"),
    # Stray script marks and bare digit runs.
    ("C\\subset D_{*}^{*}", "a) C cD;"),
    ("00400010060.", "004000 10060."),
]


@pytest.mark.parametrize("latex,ocr", AGREE)
def test_formula_agrees_with_its_ocr_line(latex, ocr):
    assert formula_agreement(latex, ocr)["code"] == "FORMULA_OCR_AGREED"


@pytest.mark.parametrize("latex,ocr", REJECT)
def test_formula_noise_is_not_verified(latex, ocr):
    assert formula_agreement(latex, ocr) is None


def test_near_match_is_only_consistent():
    result = formula_agreement("\\Delta=b^{2}-4ac>0", "có biệt thức A = bŸ - 4ac >0”.")
    assert result["code"] == "FORMULA_OCR_CONSISTENT"


def test_table_keeps_only_cells_both_readings_agree_on():
    cells = [
        {"row": 0, "column": 0, "text": "“hoi gian", "cell_local_reading": "Thời gian"},
        {"row": 0, "column": 1, "text": "30-12-2020"},
        {"row": 1, "column": 0, "text": "Giá"},
        {"row": 1, "column": 1, "text": "43—-43=0", "cell_local_reading": "43--43=0"},
    ]
    result = table_agreement(cells)
    assert result["code"] == "TABLE_CELLS_PARTIAL"
    assert result["text"] == "? | 30-12-2020\nGiá | 43—-43=0"
    assert table_agreement([{"row": 0, "column": 0, "text": "a", "cell_local_reading": "b"}]) is None


def _ocr(block_id, text, y, conf=0.95, x2=390):
    return {"block_id": block_id, "block_type": "Text", "bbox": [10, y, x2, y + 20], "text": text,
            "source": "tesseract_fast", "confidence": conf, "review_flags": []}


def _equation(block_id, latex, box):
    return {"block_id": block_id, "block_type": "Equation", "bbox": box, "text": "", "latex": [latex],
            "latex_validation": [{"valid": True}], "source": "structured_region", "confidence": None,
            "review_flags": [{"code": "STRUCTURED_EXTRACTION_REVIEW", "severity": "warning"}]}


def _doc(blocks, regions=None):
    page = {"page_id": 1, "page_size": [400, 300], "processing_status": "ok", "review": [], "blocks": blocks}
    if regions is not None:
        page["structured_enrichment"] = {"image_size": [400, 300], "regions": regions}
    return build_canonical([page], "sgk.pdf", SHA, "t", expected_pages=[1])


def test_verified_formula_is_indexed_after_its_line_and_replaces_a_garbled_one():
    doc = _doc([
        _ocr("intro", "Ta có định lí côsin:", 10),
        _ocr("garbled", "a’ = b* +c? -2bccosA,", 40, conf=0.66),
        _ocr("after", "Tương tự cho các cạnh còn lại.", 70),
        # Appended at the end by enrichment, as in real exports.
        _equation("eq", "a^{2}=b^{2}+c^{2}-2bc\\cos A", [10, 40, 300, 60]),
    ])
    assert [b["block_id"] for b in doc["pages"][0]["blocks"]] == ["intro", "garbled", "eq", "after"]
    quality = audit_canonical(doc)["quality"]
    assert quality["page_quality"][0]["hold_reasons"] == {"garbled": ["FORMULA_LINE_SUPERSEDED"]}
    blocks = {b["block_id"]: b for b in iter_retrievable_blocks(doc)}
    assert set(blocks) == {"intro", "eq", "after"}
    assert blocks["eq"]["verification"] == "verified" and blocks["intro"]["verification"] == "scored"
    # The replaced line is not a gap: the passage still reads as one window.
    assert not blocks["eq"]["after_held"]
    chunk, = build_chunks(doc, paragraph_windows=True)
    assert "a^{2}=b^{2}+c^{2}-2bc\\cos A" in chunk["text"] and not chunk["held_gap_before"]
    assert chunk["verification"] == "scored"  # weakest cited block
    assert cross_check_structured(doc) == 0  # idempotent


def test_min_verification_drops_weaker_blocks_as_gaps():
    doc = _doc([
        _ocr("intro", "Phương trình 3x” - 5x +2 =0 có nghiệm nguyên;", 10),
        _equation("eq", "3x^{2}-5x+2=0", [100, 10, 250, 30]),
        _ocr("after", "Giải phương trình.", 40),
    ])
    verified = list(iter_retrievable_blocks(doc, min_verification="verified"))
    assert [(b["block_id"], b["after_held"]) for b in verified] == [("eq", True)]
    with pytest.raises(ValueError):
        list(iter_retrievable_blocks(doc, min_verification="none"))


def test_cross_read_table_is_published_as_scored_rows():
    table = {"block_id": "t", "block_type": "Table", "bbox": [10, 100, 390, 200], "text": "",
             "table_html": "<table><tr><td>46</td><td>9</td></tr></table>",
             "source": "structured_region", "confidence": None,
             "review_flags": [{"code": c, "severity": "warning"}
                              for c in ("TABLE_OCR_REVIEW", "TABLE_HEADER_UNKNOWN", "STRUCTURED_EXTRACTION_REVIEW")]}
    reading = {"cells": [{"row": 0, "column": 0, "text": "46"}, {"row": 0, "column": 1, "text": "46-43=3"},
                         {"row": 0, "column": 2, "text": "9"}]}
    doc = _doc([_ocr("x", "Bảng độ lệch.", 10), table], regions=[{"kind": "Table", "block_id": "t", "reading": reading}])
    blocks = {b["block_id"]: b for b in iter_retrievable_blocks(doc)}
    assert blocks["t"]["text"] == "46 | 46-43=3 | 9" and blocks["t"]["verification"] == "scored"


def test_numbered_capitals_title_is_a_section_not_a_question():
    assert numbered_heading("1. MỆNH ĐỀ, MỆNH ĐỀ CHỨA BIẾN")
    assert numbered_heading("2.CAC TAP HOP SO")  # OCR lost the diacritics
    assert not numbered_heading("1. Tính giới hạn sau:")
    assert not numbered_heading("12. VIỆT NAM CÓ BAO NHIÊU TỈNH?")
    # Activity labels; the OCR'd icon digit before them is not a question number.
    for label in ("3 Luyện tập 2. Cho hình thang cân", "3 ví dụ 4. Hãy giải", "> HĐ2. Cho hai vectơ",
                  "3 Vận dung. Hai ca nô"):
        assert textbook_boundary(label), label
    for prose in ("Ví dụ như sau", "Luyện tập thêm ở nhà", "Câu 3. Cho hàm số", "1. Tính giới hạn"):
        assert not textbook_boundary(prose), prose
    page = {"page_id": 1, "page_size": [400, 300], "blocks": [
        _ocr("h", "1. MỆNH ĐỀ, MỆNH ĐỀ CHỨA BIẾN", 0),
        _ocr("s", "a. Mệnh đề", 30),
        _ocr("p", "Mỗi mệnh đề phải hoặc đúng hoặc sai.", 60),
        _ocr("q", "b) Câu nào sai?", 90),
    ], "review": []}
    result = analyze_questions([page])
    # The section title no longer swallows the whole section as "question 1".
    assert not any(g.get("number") == "1" for g in result["groups"])


def test_guessed_group_is_not_forced_into_one_chunk():
    lines = [_ocr(f"b{i}", f"Đoạn văn số {i} của mục sách giáo khoa có nhiều chữ.", 10 + 12 * i) for i in range(20)]
    for line in lines:
        line["bbox"][3] = line["bbox"][1] + 10
    doc = _doc(lines)
    doc["question_groups"] = [{"id": "g", "status": "needs_review",
                               "source_blocks": [{"block_id": b["block_id"]} for b in lines]}]
    guessed = build_chunks(doc, max_tokens=32)
    assert len(guessed) > 1 and all(c["question_id"] == "g" for c in guessed)
    doc["question_groups"][0]["status"] = "grouped_source"
    assert len(build_chunks(doc, max_tokens=32)) == 1
