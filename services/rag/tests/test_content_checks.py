"""Gate holds that say nothing about a block's text, contradicting OCR, held-heading context."""

from idp.canonical import audit_canonical, build_canonical, stamp_publish_decisions
from idp.validation import content_checks
from rag.indexing import canonical_to_markdown
from rag.search.retrieval_plan import terms

SHA = "e" * 64


def block(block_id, text, y, *, source="paddleocr_vl_gguf", confidence=0.99, flags=(), block_type="Text"):
    return {
        "block_id": block_id, "block_type": block_type, "bbox": [10, y, 390, y + 20], "text": text,
        "source": source, "confidence": confidence,
        "review_flags": [f if isinstance(f, dict) else {"code": f, "severity": "warning"} for f in flags],
    }


def disagree(alternative):
    return {"code": "OCR_REGION_DISAGREEMENT", "severity": "warning",
            "recovery_region_id": "r000", "alternative": alternative}


def holds(blocks):
    page = {"page_id": 1, "page_size": [400, 300], "processing_status": "ok", "review": [], "blocks": blocks}
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    quality = audit_canonical(doc)["quality"]["page_quality"][0]
    return quality["hold_reasons"], quality["resolved_holds"]


def test_budget_exhaustion_does_not_hold_good_plain_text():
    reasons, resolved = holds([
        block("plain", "khoảng hay nửa khoảng.", 10, source="tesseract_ocr", confidence=0.96,
              flags=["STRUCTURED_BUDGET_EXHAUSTED"]),
        block("math", "a < x \\leq b", 40, source="tesseract_ocr", confidence=0.96,
              flags=["STRUCTURED_BUDGET_EXHAUSTED"]),
        block("weak", "Nửa khoảng", 70, source="tesseract_ocr", confidence=0.70,
              flags=["STRUCTURED_BUDGET_EXHAUSTED"]),
    ])
    assert "plain" not in reasons and resolved["plain"] == ["STRUCTURED_BUDGET_EXHAUSTED"]
    assert reasons["math"] == ["STRUCTURED_BUDGET_EXHAUSTED"]  # structure was needed
    assert reasons["weak"] == ["STRUCTURED_BUDGET_EXHAUSTED"]  # below 0.80


def test_presentation_only_disagreement_is_resolved():
    garbled = "Do đó sinA =A/1- cos? A =0,8."
    reasons, resolved = holds([
        block("sin", "Do do $\\sin A = \\sqrt{1 - \\cos^{2}A} = 0,8$.", 10, flags=[disagree(garbled)]),
        # The region-level alternative reads the line below, not this one.
        block("cos", "$$\\cos A = \\frac{b^{2} + c^{2} - a^{2}}{2bc} = 0,6.$$", 40, flags=[disagree(garbled)]),
    ])
    assert reasons == {}
    assert resolved == {"sin": ["OCR_REGION_DISAGREEMENT"], "cos": ["OCR_REGION_DISAGREEMENT"]}


def test_content_disagreement_still_holds():
    reasons, _ = holds([
        # A different word: Tesseract "ẩn" is right, the primary "lần" is not.
        block("word", "Hệ bất phương trình bậc nhất hai lần?", 10,
              flags=[disagree("Hệ bắt phương trình bậc nhát hai ẩn?")]),
        block("number", "Tổng bằng 26.", 40, flags=[disagree("Tổng bằng 28.")]),
        block("relation", "17 ∉ D", 70, flags=[disagree("17 ∈ D")]),
        block("digit", "KÉO THE0", 100, flags=[disagree("KÉO THEO")]),
        block("lowconf", "Tổng bằng 26.", 130, confidence=0.85, flags=[disagree("Tổng bằng 26 .")]),
    ])
    assert set(reasons) == {"word", "number", "relation", "digit", "lowconf"}
    assert all(r == ["OCR_REGION_DISAGREEMENT"] for r in reasons.values())


def test_set_membership_contradiction_holds_the_statement():
    reasons, _ = holds([
        block("def", "a) $D = \\{7; 11; 13; 17; 19\\}$. Tập hợp $D$ có 5 phần tử.", 10),
        block("bad", "b) $5 ∉ D; $12 ∉ D; $17 ∉ D; $18 ∉ D.", 40),
        block("good", "Ta có 13 \\in D và 12 \\notin D.", 70),
    ])
    assert reasons == {"bad": ["MATH_SET_MEMBERSHIP_CONFLICT"]}


def test_membership_check_needs_one_unambiguous_enumeration():
    page = [
        block("d1", "D = {1; 2}", 10),
        block("d2", "D = {3; 4}", 40),
        block("s", "1 ∉ D", 70),
    ]
    assert content_checks.membership_conflicts(page) == set()
    assert content_checks.membership_conflicts([block("s", "1 ∉ D", 10)]) == set()


def _stamped(blocks):
    page = {"page_id": 1, "page_size": [400, 300], "processing_status": "ok", "review": [], "blocks": blocks}
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    stamp_publish_decisions(doc, audit_canonical(doc))
    return doc


def test_held_heading_names_the_section_of_an_orphan_formula():
    doc = _stamped([
        block("h", "2. CÁC TÍNH CHẤT CỦA PHÉP NHÂN VECTƠ VỚI MỘT SỐ", 10, confidence=0.27,
              flags=["LOW_CONFIDENCE"], block_type="SectionHeader"),
        block("lead", "Vói hai vẹcto đ, b ta luôn có:", 40, confidence=0.23, flags=["LOW_CONFIDENCE"]),
        block("f", "k(\\vec{a}+\\vec{b})=k\\vec{a}+k\\vec{b}", 70, block_type="Equation"),
    ])
    held = {b["block_id"]: b["held"] for b in doc["pages"][0]["blocks"]}
    assert held == {"h": True, "lead": True, "f": False}
    text, ranges = canonical_to_markdown(doc)
    assert text == "## 2. CÁC TÍNH CHẤT CỦA PHÉP NHÂN VECTƠ VỚI MỘT SỐ\n\nk(\\vec{a}+\\vec{b})=k\\vec{a}+k\\vec{b}"
    assert ranges[0]["sections"][0]["title"].startswith("2. CÁC TÍNH CHẤT")
    assert "Vói" not in text  # held body text stays out


def test_held_heading_is_not_context_without_body_or_with_a_content_hold():
    no_body = _stamped([
        block("h", "Mục bị giữ", 10, confidence=0.27, flags=["LOW_CONFIDENCE"], block_type="SectionHeader"),
        block("h2", "Mục kế tiếp", 40, block_type="SectionHeader"),
        block("t", "Nội dung.", 70),
    ])
    assert canonical_to_markdown(no_body)[0] == "## Mục kế tiếp\n\nNội dung."
    hard = _stamped([
        block("h", "x^{2", 10, flags=["LATEX_INVALID"], block_type="SectionHeader"),
        block("t", "Nội dung.", 40),
    ])
    assert canonical_to_markdown(hard)[0] == "Nội dung."


def test_search_terms_match_typed_math():
    assert {"y1/y2", "y1", "y2", "c1"} <= set(terms("\\frac{y_{1}}{y_{2}} = c_{1}"))
    assert "y1/y2" in terms("y1/y2 = c1")
    assert {"cos", "sin", "α", "β"} <= set(terms("e^{\\alpha x}(C_{1}\\cos\\beta x+C_{2}\\sin\\beta x)"))
    assert terms("AB² + AC² = BC²") == terms("AB^{2} + AC^{2} = BC^{2}")
    assert terms("y_1 + y_2") == terms("y1 + y2")
    assert terms("x \\in \\mathbb{R}") == terms("x ∈ ℝ") == ["x", "r"]
