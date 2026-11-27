"""The audit's retrieval decision is written onto canonical blocks."""

from idp.canonical import audit_canonical, build_canonical, stamp_publish_decisions

SHA = "d" * 64


def text_block(block_id, text, y, source="tesseract_fallback", confidence=0.95, flags=(), block_type="Text"):
    return {
        "block_id": block_id, "block_type": block_type, "bbox": [10, y, 390, y + 20], "text": text,
        "source": source, "confidence": confidence,
        "review_flags": [{"code": c, "severity": "warning"} for c in flags],
    }


def ok_page(page_id, blocks, review=()):
    return {"page_id": page_id, "page_size": [400, 300], "processing_status": "ok",
            "review": [{"code": c, "severity": "warning"} for c in review], "blocks": blocks}


def test_block_and_page_holds_are_stamped_and_restamping_is_stable():
    pages = [
        ok_page(1, [
            text_block("a", "Đọc tốt.", 10),
            text_block("b", "Đọc kém.", 40, confidence=0.3, flags=["LOW_CONFIDENCE"]),
            text_block("h", "Chương 1", 0, block_type="PageHeader"),
            {**text_block("f", "", 70, source="paddle_formula", confidence=None,
                          flags=["STRUCTURED_EXTRACTION_REVIEW"], block_type="Equation"),
             "markdown": "$$x^2$$", "latex": ["x^2"]},
        ]),
        ok_page(2, [text_block("c", "Trang bị giữ.", 10)], review=["STRUCTURED_BUDGET_EXHAUSTED"]),
    ]
    doc = build_canonical(pages, "f.pdf", SHA, "t", expected_pages=[1, 2])
    report = audit_canonical(doc)

    assert stamp_publish_decisions(doc, report) == 3
    blocks = {b["block_id"]: b for page in doc["pages"] for b in page["blocks"]}
    assert blocks["a"]["held"] is False and "hold_reasons" not in blocks["a"]
    assert blocks["b"]["held"] is True and "LOW_CONFIDENCE" in blocks["b"]["hold_reasons"]
    assert blocks["c"]["held"] is True
    assert blocks["c"]["hold_reasons"] == ["STRUCTURED_BUDGET_EXHAUSTED"]
    assert "held" not in blocks["h"]  # running header, not audited
    assert blocks["f"]["held"] is True  # model LaTeX only in markdown
    assert doc["publish_decision"]["held_blocks"] == 3

    # The stamp does not change the audit, and stamping again is idempotent.
    again = audit_canonical(doc)
    assert again["quality"]["page_quality"] == report["quality"]["page_quality"]
    assert stamp_publish_decisions(doc, again) == 3
