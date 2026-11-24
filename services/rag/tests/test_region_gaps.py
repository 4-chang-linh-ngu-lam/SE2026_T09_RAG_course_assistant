"""Held gaps for untranscribed regions, gap markers and block-policy contracts."""

from PIL import Image
import pytest

from idp.canonical import audit_canonical, build_canonical
from idp.documents.digital import _encoding_issues
from idp.documents.text_math import _encoding_problem
from idp.ocr.recovery import RecoveryOptions, recover_text_regions
from idp.structured.enrichment import EnrichmentOptions, RegionEnricher
from rag.retrieval.canonical_harness import (
    build_chunks,
    citation_index,
    iter_retrievable_blocks,
    resolve_citation,
)

SHA = "c" * 64


def text_block(block_id, text, y, source="pdf_text", confidence=None, flags=()):
    return {
        "block_id": block_id, "block_type": "Text", "bbox": [10, y, 390, y + 20], "text": text,
        "source": source, "confidence": confidence,
        "review_flags": [{"code": c, "severity": "warning"} for c in flags],
    }


def ok_page(page_id, blocks, review=()):
    return {"page_id": page_id, "page_size": [400, 300], "processing_status": "ok",
            "review": [{"code": c, "severity": "warning"} for c in review], "blocks": blocks}


def test_structured_pixel_limit_leaves_a_held_placeholder_that_splits_text(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 300), "white").save(image)
    page = ok_page(1, [text_block("above", "Định nghĩa như sau:", 10),
                       text_block("below", "Khi đó hàm số liên tục.", 200)])
    enricher = RegionEnricher(lambda _: [{"kind": "equation", "bbox": [10, 100, 390, 160]}],
                              options=EnrichmentOptions(max_crop_pixels=100))
    report = enricher.enrich_page(page, tmp_path, image)
    assert [r["status"] for r in report["regions"]] == ["pixel_limit"]
    gap_id = report["regions"][0]["block_id"]
    # Inserted in reading order, between the two text blocks.
    assert [b["block_id"] for b in page["blocks"]] == ["above", gap_id, "below"]

    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    audit = audit_canonical(doc, trusted_parsers={"pdf_text"})
    assert audit["pass"]
    quality = audit["quality"]
    assert quality["auto_publish_pages"] == [1]
    assert gap_id in quality["held_blocks"]
    assert "STRUCTURED_PIXEL_LIMIT" in quality["page_quality"][0]["hold_reasons"][gap_id]

    blocks = {b["block_id"]: b for b in iter_retrievable_blocks(doc, trusted_parsers={"pdf_text"})}
    assert blocks["above"]["before_held"] and not blocks["above"]["after_held"]
    assert blocks["below"]["after_held"]
    chunks = build_chunks(doc, trusted_parsers={"pdf_text"}, paragraph_windows=True)
    assert len(chunks) == 2  # never joined across the missing formula
    assert [(c["held_gap_before"], c["held_gap_after"]) for c in chunks] == [(False, True), (True, False)]


def test_region_loss_code_without_owning_block_holds_the_page():
    # An artifact from before placeholders: the gap has no position.
    page = ok_page(1, [text_block("a", "Prose.", 10)], review=["STRUCTURED_BUDGET_EXHAUSTED"])
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    quality = audit_canonical(doc, trusted_parsers={"pdf_text"})["quality"]
    assert quality["auto_publish_pages"] == []
    assert quality["page_quality"][0]["page_gating_codes"] == ["STRUCTURED_BUDGET_EXHAUSTED"]


def test_recovery_records_every_skipped_region_and_canonical_holds_them(tmp_path):
    image = tmp_path / "scan.png"
    Image.new("RGB", (400, 300), "white").save(image)
    regions = [{"kind": "text", "bbox": [10, 50, 390, 90]}, {"kind": "text", "bbox": [10, 120, 390, 160]}]
    lines, report = recover_text_regions(
        image, [], tmp_path / "work", detector=lambda _: regions,
        options=RecoveryOptions(max_regions=1), read_crop=lambda crop, timeout: [],
    )
    assert report["image_size"] == [400, 300]
    assert [r["status"] for r in report["regions"]] == ["unresolved", "budget_limit"]
    assert {f["code"] for f in report["flags"]} == {"OCR_REGION_UNRESOLVED", "OCR_REGION_BUDGET_EXHAUSTED"}

    page = ok_page(1, [text_block("t0", "Đoạn đầu.", 10, "tesseract_fallback", .95),
                       text_block("t1", "Đoạn giữa.", 95, "tesseract_fallback", .95),
                       text_block("t2", "Đoạn cuối.", 200, "tesseract_fallback", .95)],
                   review=[f["code"] for f in report["flags"]])
    page["region_recovery"] = report
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    assert [b["block_id"] for b in doc["pages"][0]["blocks"]] == [
        "t0", "p0001_gap_r000", "t1", "p0001_gap_r001", "t2"]
    audit = audit_canonical(doc)
    assert audit["pass"]
    quality = audit["quality"]
    assert quality["auto_publish_pages"] == [1]
    assert quality["held_blocks"] == ["p0001_gap_r000", "p0001_gap_r001"]
    blocks = list(iter_retrievable_blocks(doc))
    assert [(b["after_held"], b["before_held"]) for b in blocks] == [(False, True), (True, True), (True, False)]


def test_legacy_structured_report_is_materialized_once():
    # As written before placeholders: the skipped region is only in the report,
    # and an unresolved table carries TABLE_EMPTY but not the page code.
    table = {"block_id": "p0001_s000", "block_type": "Table", "bbox": [10, 200, 390, 280], "text": "",
             "source": "structured_region", "confidence": None,
             "review_flags": [{"code": "TABLE_EMPTY", "severity": "warning"}]}
    page = ok_page(1, [text_block("above", "Trước công thức.", 10, "tesseract_fast", .95),
                       text_block("below", "Sau công thức.", 150, "tesseract_fast", .95), table],
                   review=["STRUCTURED_BUDGET_EXHAUSTED", "STRUCTURED_REGION_UNRESOLVED",
                           "STRUCTURED_EXTRACTION_REVIEW"])
    page["structured_enrichment"] = {"image_size": [800, 600], "regions": [
        {"kind": "Table", "status": "unresolved", "block_id": "p0001_s000", "pixel_bbox": [20, 400, 780, 560]},
        {"kind": "Equation", "status": "budget_limit", "recognition_skipped": "budget_limit",
         "block_id": None, "pixel_bbox": [20, 100, 780, 260]},
    ]}
    from idp.canonical import materialize_region_gaps

    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    assert [b["block_id"] for b in doc["pages"][0]["blocks"]] == ["above", "p0001_gap_s001", "below", "p0001_s000"]
    gap = doc["pages"][0]["blocks"][1]
    assert gap["bbox"] == [10.0, 50.0, 390.0, 130.0]  # image pixels -> page units
    assert materialize_region_gaps(doc) == 0  # idempotent
    quality = audit_canonical(doc)["quality"]
    assert quality["auto_publish_pages"] == [1]
    assert set(quality["held_blocks"]) == {"p0001_gap_s001", "p0001_s000"}

    # An already-built document without gaps is upgraded in place.
    legacy = build_canonical([{**page, "structured_enrichment": None}], "f.pdf", SHA, "t", expected_pages=[1])
    for canonical_page in legacy["pages"]:
        canonical_page["structured_enrichment"] = page["structured_enrichment"]
    assert audit_canonical(legacy)["quality"]["auto_publish_pages"] == []
    assert materialize_region_gaps(legacy) == 1
    assert materialize_region_gaps(legacy) == 0
    assert audit_canonical(legacy)["quality"]["auto_publish_pages"] == [1]


def test_recovery_report_without_image_size_fails_closed():
    page = ok_page(1, [text_block("t0", "Đoạn.", 10, "tesseract_fallback", .95)],
                   review=["OCR_REGION_UNRESOLVED"])
    page["region_recovery"] = {"regions": [{"region_id": "r000", "bbox": [10, 50, 390, 90], "status": "unresolved"}]}
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    quality = audit_canonical(doc)["quality"]
    assert quality["auto_publish_pages"] == []
    assert quality["page_quality"][0]["page_gating_codes"] == ["OCR_REGION_UNRESOLVED"]


def test_recovery_disagreement_holds_the_disagreeing_block():
    page = ok_page(1, [text_block("t0", "KÉO THE0", 50, "tesseract_fallback", .95),
                       text_block("t1", "Khác.", 200, "tesseract_fallback", .95)],
                   review=["OCR_REGION_DISAGREEMENT", "OCR_REGION_RECOVERED"])
    page["region_recovery"] = {"image_size": [400, 300], "regions": [{
        "region_id": "r000", "bbox": [10, 40, 390, 80], "status": "recovered",
        "alternatives": [{"text": "KÉO THEO", "bbox": [10, 50, 390, 70]}]}]}
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    quality = audit_canonical(doc)["quality"]
    assert quality["auto_publish_pages"] == [1]
    assert quality["page_quality"][0]["hold_reasons"] == {"t0": ["OCR_REGION_DISAGREEMENT"]}


def test_running_line_filter_keeps_the_gap_marker():
    # A held formula placeholder has no text, so the page number after it is
    # the page's first text line and is dropped as a running line.
    held = text_block("held", "", 0, "structured_region", None, ["STRUCTURED_PIXEL_LIMIT", "EMPTY_BLOCK"])
    page = ok_page(1, [held,
                       text_block("folio", "12", 30, "tesseract_fallback", .95),
                       text_block("prev", "Phần trước.", 60, "tesseract_fallback", .95),
                       text_block("next", "Tiếp tục chứng minh.", 100, "tesseract_fallback", .95)])
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    assert [b["after_held"] for b in iter_retrievable_blocks(doc)] == [True, False, False]
    chunks = build_chunks(doc, paragraph_windows=True)
    assert "12" not in {c["text"] for c in chunks}
    first, = [c for c in chunks if c["text"].startswith("Phần trước.")]
    assert first["held_gap_before"]


def test_holed_needs_review_group_is_one_incomplete_unit():
    page = ok_page(1, [
        text_block("q1", "1. Tính giới hạn sau:", 10, "tesseract_fallback", .95),
        text_block("q1x", "lim x→0", 40, "tesseract_fallback", .30, ["LOW_CONFIDENCE"]),
        text_block("q1a", "A. 0", 70, "tesseract_fallback", .95),
        text_block("memo", "Ghi chú cuối trang.", 250, "tesseract_fallback", .95),
    ])
    doc = build_canonical([page], "f.pdf", SHA, "t", expected_pages=[1])
    doc["question_groups"] = [
        {"id": "g1", "status": "needs_review", "source_blocks": [
            {"block_id": "q1"}, {"block_id": "q1x"}, {"block_id": "q1a"}]},
        {"id": "g2", "status": "needs_review", "source_blocks": [{"block_id": "memo"}, {"block_id": "gone"}]},
    ]
    chunks = {c["text"]: c for c in build_chunks(doc)}
    # Not loose fragments: the remaining members stay together, marked.
    joined = "1. Tính giới hạn sau:\n\nA. 0"
    assert set(chunks) == {joined, "Ghi chú cuối trang."}
    question = chunks[joined]
    assert question["question_id"] == "g1" and question["question_incomplete"]
    # A guess missing only a non-held block keeps the old behavior.
    memo = chunks["Ghi chú cuối trang."]
    assert memo["question_id"] is None and not memo["question_incomplete"]


def test_policy_contract_and_untrusted_rebuild():
    rebuilt = text_block("m", "f(x) = x^{2}", 10)
    rebuilt["review_flags"] = [{"code": "FORMULA_TEXT_LAYER_RECONSTRUCTED", "severity": "info"}]
    doc = build_canonical([ok_page(1, [rebuilt])], "f.pdf", SHA, "t", expected_pages=[1])
    # A lossless rebuild of an untrusted text layer is not verification.
    quality = audit_canonical(doc, trusted_parsers=set())["quality"]
    assert quality["auto_publish_pages"] == []  # its only text block is held
    assert quality["page_quality"][0]["published_blocks"] == 0
    trusted = audit_canonical(doc, trusted_parsers={"pdf_text"})["quality"]
    assert trusted["retrievable_by_verification"] == {"trusted": {"blocks": 1, "chars": 12}}
    assert trusted["retrievable_block_rate"] == 1.0
    # block_scoped_codes imply the page policy; contradicting them is an error.
    assert audit_canonical(doc, block_scoped_codes={"X"})["quality"]["publish_policy"] == "page"
    with pytest.raises(ValueError):
        audit_canonical(doc, block_scoped_codes={"X"}, policy="block")
    with pytest.raises(ValueError):
        list(iter_retrievable_blocks(doc, block_scoped_codes={"X"}, policy="block"))


def test_citation_index_is_reusable_and_bound_to_its_document():
    doc = build_canonical([ok_page(1, [text_block("a", "Một câu trích dẫn.", 10)])],
                          "f.pdf", SHA, "t", expected_pages=[1])
    chunk, = build_chunks(doc, trusted_parsers={"pdf_text"})
    index = citation_index(doc, trusted_parsers={"pdf_text"})
    cite, = resolve_citation(chunk, doc, index=index)
    assert cite["text"] == "Một câu trích dẫn."
    other = {**doc, "source_sha256": "d" * 64}
    with pytest.raises(ValueError):
        resolve_citation(chunk, other, index=index)


def test_rebuild_and_digital_audit_agree_on_encoding():
    text = "Ký hiệu y(·) = (y_{1}(·), y_{2}(·), . . . , y_{n}(·))^{⊤} là nghiệm"
    assert _encoding_issues(text) == [] and not _encoding_problem(text)
    substituted = "Đ·nh l· c·a h·m s·"
    assert _encoding_issues(substituted) == ["middle_dot_substitution"]
    assert _encoding_problem(substituted)
    # Every digital finding is also a rebuild finding (the invariant).
    for sample in ("a�b", "(cid:12) x", "x\x11y", substituted):
        assert bool(_encoding_issues(sample)) <= _encoding_problem(sample)
