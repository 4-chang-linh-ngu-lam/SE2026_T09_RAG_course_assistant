import argparse
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from idp.canonical import audit_canonical
from idp.documents.digital import (
    _encoding_issues,
    _native_reading_order,
    _pdf_span_gap,
    _pdf_span_text,
)
from idp.documents.layout import prepare_page_figures
from idp.ocr import local_region
from idp.ocr.fast import parse_hocr_lines
from idp.structured.enrichment import (
    EnrichmentOptions,
    RegionEnricher,
    add_structured_arguments,
    structured_context,
)
from idp.structured.structure import RuledTableDetector
from idp.validation.validate import validate_latex


def test_enrichment_preserves_large_and_late_figures_with_source_geometry(tmp_path):
    page_image = tmp_path / "page.png"
    Image.new("RGB", (400, 300), "white").save(page_image)
    page = {"page_id": 1, "page_size": [400, 300], "blocks": [], "review": []}
    proposals = [
        {"kind": "equation", "bbox": [10, 250, 60, 270]},
        {"kind": "image", "bbox": [20, 20, 150, 220]},
        {"kind": "image", "bbox": [18, 20, 200, 222]},
        {"kind": "chart", "bbox": [250, 70, 350, 160]},
    ]

    def recognize(path, timeout):
        with Image.open(path) as crop:
            assert crop.width * crop.height <= 10_000
            return {"labels": [{"text": "x", "bbox": [0, 0, crop.width, crop.height]}]}

    labels = Mock(side_effect=recognize)
    enricher = RegionEnricher(lambda _: proposals, options=EnrichmentOptions(max_regions=1, max_crop_pixels=10_000),
                              label_reader=labels)
    result = enricher.enrich_page(page, tmp_path, page_image)
    assert [r["status"] for r in result["regions"]] == ["image_preserved", "image_preserved", "budget_limit"]
    assert len(result["regions"][0]["layout_boxes"]) == 2
    assert result["regions"][1]["recognition_skipped"] == "budget_limit"
    assert labels.call_count == 1
    first = page["blocks"][0]
    with Image.open(first["block_crop_path"]) as crop:
        assert crop.size == (182, 202)
    assert first["visual_labels"][0]["pixel_bbox"] == [18, 20, 200, 222]


def test_figure_caption_and_markdown_survive_export_relocation(tmp_path):
    asset = tmp_path / "assets" / "chart.png"
    asset.parent.mkdir()
    Image.new("RGB", (10, 10)).save(asset)
    figure = {"block_id": "chart", "block_type": "Chart", "bbox": [20, 20, 120, 120], "asset_paths": [str(asset)]}
    caption = {"block_id": "caption", "block_type": "Text", "bbox": [30, 125, 110, 140], "text": "Hình T.1a"}
    page = {"page_size": [200, 200], "blocks": [figure, caption]}
    prepare_page_figures(page, tmp_path)
    assert figure["caption"] == caption["text"]
    assert figure["markdown"] == "![Hình T.1a](../assets/chart.png)"
    exported = {
        "pages": [{"page_id": 1, "status": "ok", "blocks": [
            {"type": "Chart", "block_id": "chart", "source": "test", "asset_paths": ["/results/output/assets/chart.png"]},
        ]}],
    }
    audit = audit_canonical(exported, asset_path_mapping=("/results/output", tmp_path))
    assert audit["checks"]["assets_present"]["pass"]
    exported["pages"][0]["blocks"][0]["asset_paths"] = ["/results/output/../outside.png"]
    audit = audit_canonical(exported, asset_path_mapping=("/results/output", tmp_path))
    assert not audit["checks"]["assets_present"]["pass"]


def test_structured_regions_use_loopback_gguf_for_formulas(monkeypatch):
    read = Mock(return_value={"latex": "x^2"})
    monkeypatch.setattr(local_region, "read_region", read)
    parser = argparse.ArgumentParser()
    add_structured_arguments(parser)
    args = parser.parse_args(["--structured-regions", "--formula-gguf-url", "http://127.0.0.1:8111"])
    with structured_context(args, parser, detector=object()) as enricher:
        assert enricher.formula_reader("crop.png", 3) == {"latex": "x^2"}
        assert not enricher.cacheable
    read.assert_called_once_with(
        "crop.png", "Equation", base_url="http://127.0.0.1:8111", timeout=3,
        max_tokens=512, model="paddleocr-vl-1.6", prompt_profile="paddleocr",
    )
    with pytest.raises(local_region.LocalRegionError, match="loopback"):
        local_region.PaddleGGUFFormulaReader("https://example.com")


def test_latex_checks_delimiter_commands_without_matching_arrows():
    reaction = r"^{14}_{6}C\rightarrow{^{14}_{7}N}+e^{-}+\overline{{{\nu}}}_{e}"
    assert validate_latex(reaction).valid
    assert validate_latex(r"\left(x\leftarrow y\right)").valid
    assert not validate_latex(r"x\right)").valid
    assert not validate_latex(r"\right)x\left(").valid


def test_native_formula_fragments_on_the_same_row_read_left_to_right():
    lead = {"kind": "text", "bbox": [141.7, 509.0, 283.9, 519.9], "size": 11}
    matrix = {"kind": "text", "bbox": [294.8, 502.2, 316.3, 526.7], "size": 11}
    right = {"kind": "text", "bbox": [326.0, 509.0, 495.9, 521.6], "size": 11}
    assert _native_reading_order([matrix, right, lead]) == [lead, matrix, right]
    assert _encoding_issues("a + · · · + z") == []
    assert _encoding_issues("a ·b ·c ·d") == ["middle_dot_substitution"]


def test_native_spacing_respects_math_glyph_gap_between_spans():
    left = {"chars": [{"c": "ụ", "bbox": (20, 0, 25, 10)}]}
    right = {"size": 8, "chars": [{"c": "1", "origin": (29, 8)}]}
    assert _pdf_span_gap(left, right)
    right["chars"][0]["origin"] = (25.5, 8)
    assert not _pdf_span_gap(left, right)


def test_hocr_keeps_independent_line_types_and_their_geometry():
    def line(kind, text, top):
        return (
            f'<span class="ocr_{kind}" title="bbox 0 {top} 90 {top + 12}">'
            f'<span class="ocrx_word" title="bbox 1 {top} 70 {top + 12}; x_wconf 99">'
            f'<strong>{text}</strong></span></span>'
        )

    hocr = "".join(line(kind, text, index * 20) for index, (kind, text) in enumerate(
        [("header", "Ví dụ 6",), ("line", "a = 13"), ("textfloat", "Ghi chú"), ("caption", "Hình 3.17")]
    ))
    lines = parse_hocr_lines(hocr)
    assert [item["text"] for item in lines] == ["Ví dụ 6", "a = 13", "Ghi chú", "Hình 3.17"]
    assert [item["bbox"][1] for item in lines] == [0, 20, 40, 60]


def test_native_spacing_uses_glyph_gap_inside_prose_span():
    chars = [
        {"c": char, "origin": (left, 10), "bbox": (left, 0, right, 10)}
        for char, left, right in [("x", 0, 5), ("ạ", 5, 10), ("l", 14, 16), ("à", 16, 21)]
    ]
    assert _pdf_span_text({"font": "LMRoman10-Regular", "size": 11, "chars": chars}, horizontal=True) == "xạ là"
    assert _pdf_span_text({"font": "LMMathItalic10-Regular", "size": 11, "chars": chars}, horizontal=True) == "xạlà"


def test_cpu_detector_finds_ruled_grid_with_merged_cell_but_not_callout(tmp_path):
    image = Image.new("RGB", (600, 650), "white")
    draw = ImageDraw.Draw(image)
    cyan = (50, 220, 225)
    draw.rectangle((40, 80, 345, 400), outline=cyan, width=3)
    for y in (160, 240, 320):
        draw.line((40, y, 345, y), fill=cyan, width=3)
    draw.line((145, 80, 145, 320), fill=cyan, width=3)
    draw.line((245, 80, 245, 400), fill=cyan, width=3)
    draw.rectangle((388, 112, 565, 379), outline=cyan, width=3)
    target = tmp_path / "grid.png"
    image.save(target)

    regions = RuledTableDetector()(target)
    assert len(regions) == 1
    assert regions[0]["kind"] == "table"
    assert all(abs(actual - expected) < 6 for actual, expected in zip(regions[0]["bbox"], (40, 80, 346, 401)))
