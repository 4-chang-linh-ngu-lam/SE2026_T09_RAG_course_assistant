"""Import complete PaddleOCRVL page results into the existing ingestion lane.

Owned by tools/idp; no model downloads, network calls, service API or implicit
parser trust. Raw provider results and image hashes remain source evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re

from PIL import Image

from .filetypes import InputLimits, detect_file_type, validate_input
from .pipeline import run_pipeline
from .otsl import otsl_to_html
from .structure import parse_table_html

QUALITY_VERSION = "idp-quality-import-5"
LABELS = {
    "doc_title": "SectionHeader", "paragraph_title": "SectionHeader",
    "header": "PageHeader", "footer": "PageFooter", "figure_title": "Caption",
    "image": "Picture", "header_image": "Picture", "footer_image": "Picture",
    "chart": "Chart", "table": "Table", "display_formula": "Equation",
    "inline_formula": "Equation", "formula_number": "Text", "number": "Text",
    "text": "Text", "content": "Text", "abstract": "Text", "reference": "Text",
    "reference_content": "Text", "footnote": "Text", "vision_footnote": "Text",
    "aside_text": "Text", "algorithm": "Code", "seal": "Picture",
}
MATH = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|(?<!\\)\$([^$\n]+?)(?<!\\)\$", re.S)


def _prose_html(value):
    """Escape prose while retaining explicit model math at its original position."""
    parts, end = [], 0
    for match in MATH.finditer(value):
        parts.append(html.escape(value[end:match.start()]).replace("\n", "<br>"))
        parts.append("<math>" + html.escape(next(g for g in match.groups() if g is not None)) + "</math>")
        end = match.end()
    parts.append(html.escape(value[end:]).replace("\n", "<br>"))
    return "<p>" + "".join(parts) + "</p>"


def paddle_to_marker(raw, image_path, *, page_id, revision, completion_path=None, source_sha256=None):
    if type(page_id) is not int or page_id < 1 or not isinstance(raw, dict):
        raise ValueError("quality result requires a page object and positive page ID")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("quality parser requires an immutable runtime/model revision")
    image_path = Path(image_path).resolve()
    completion = None
    if completion_path:
        from .completion import verify_completion
        completion = verify_completion(completion_path, raw_result=raw, image_path=image_path,
            revision=revision, source_sha256=source_sha256, page=page_id)
    result = raw.get("res", raw)
    if not isinstance(result, dict) or not isinstance(result.get("parsing_res_list"), list):
        raise ValueError("quality input must contain PaddleOCRVL parsing_res_list")
    if result.get("input_path") and Path(result["input_path"]).resolve() != image_path:
        raise ValueError("quality result and source image paths do not match")
    settings = result.get("model_settings") or {}
    if settings.get("use_doc_preprocessor"):
        raise ValueError("transformed quality images require an explicit coordinate mapping")
    with Image.open(image_path) as image:
        width, height = image.size
    if (result.get("width", width), result.get("height", height)) != (width, height):
        raise ValueError("quality result dimensions do not match source pixels")
    records = result["parsing_res_list"]
    if not records or len(records) > 4096:
        raise ValueError("quality result has no regions or exceeds the region limit")
    children, seen = [], set()
    for index, source in enumerate(records):
        key = source.get("block_id", index)
        if not isinstance(key, (str, int)) or key in seen:
            raise ValueError("quality result has invalid or duplicate source region IDs")
        seen.add(key)
        box = source.get("block_bbox")
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) not in {int, float} or not math.isfinite(v) for v in box)
                or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)):
            raise ValueError("quality region bbox is not aligned with the source image")
        label = source.get("block_label")
        content = source.get("block_content")
        if not isinstance(label, str) or not isinstance(content, str) or len(content) > 32768:
            raise ValueError("invalid quality region label/content")
        kind = LABELS.get(label, "Text")
        flags = []
        supplement = source.get("idp_formula_supplement")
        if supplement is not None:
            from .inline_formula import INLINE_VERSION
            boxes = result.get("layout_det_res", {}).get("boxes", [])
            detector_index = supplement.get("detector_index") if isinstance(supplement, dict) else None
            if (not isinstance(supplement, dict) or supplement.get("version") != INLINE_VERSION
                    or label != "inline_formula" or type(detector_index) is not int
                    or not 0 <= detector_index < len(boxes)
                    or boxes[detector_index].get("label") != "inline_formula"
                    or list(box) != boxes[detector_index].get("coordinate")):
                raise ValueError("untraceable inline formula supplement")
            flags.append({"code": "INLINE_FORMULA_ALTERNATIVE_REVIEW", "severity": "warning"})
        if label not in LABELS:
            flags.append({"code": "QUALITY_LABEL_UNKNOWN", "severity": "warning"})
        if label == "number":
            flags.append({"code": "SOURCE_NUMBER_ROLE_REVIEW", "severity": "warning"})
        if kind in {"Picture", "Chart"} and content.strip():
            flags.append({"code": "QUALITY_VISUAL_TEXT_REVIEW", "severity": "warning"})
        if kind == "Table":
            fragment = otsl_to_html(content) if content.lstrip().startswith(("<fcel>", "<ecel>")) else content
            table = parse_table_html(fragment)
            if not table["rectangular"]:
                raise ValueError("quality table topology is incomplete")
        elif kind == "Equation":
            match = MATH.fullmatch(content.strip())
            value = next(g for g in match.groups() if g is not None) if match else content
            fragment = '<p><math display="block">' + html.escape(value) + "</math></p>"
        else:
            fragment = _prose_html(content)
        if not content.strip() and kind not in {"Picture", "Chart"}:
            flags.append({"code": "QUALITY_REGION_EMPTY", "severity": "warning"})
        children.append({"block_type": kind, "bbox": list(box), "html": fragment,
            "chart": kind == "Chart", "provider_review_flags": flags,
            "excluded_from_content": label in {"header", "footer", "header_image", "footer_image"}
                and label in settings.get("markdown_ignore_labels", []),
            "source_evidence": {"provider": "paddleocr_vl", "region_id": key,
                "label": label, "reading_order": source.get("block_order"),
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                **({"inline_formula_supplement": supplement} if supplement is not None else {}),
                "export_policy": "provider_running_margin" if label in {"header", "footer", "header_image", "footer_image"}
                    and label in settings.get("markdown_ignore_labels", []) else "preserve_content"}})
    return {"metadata": {"engine": "paddleocr_vl", "version": revision, "kind": "ocr", "page": page_id,
        "quality_source": {"adapter": QUALITY_VERSION, "revision": revision,
            "source_image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "raw_result_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "source_regions": len(records), "imported_regions": len(children),
            "recognition_completeness": "verified" if completion else "unverified",
            "completion": completion}},
        "children": [{"block_type": "Page", "bbox": [0, 0, width, height], "children": children}]}


def ingest_quality(input_path, out_dir, page_results, *, revision, language="vie+eng",
        figure_cmd=None, figure_revision=None, figure_timeout=15, structured_regions=False,
        label_detector_model_dir=None,rectify_labels=False):
    """Use full quality parsing as the source lane, then canonical + chunks.

    ``page_results`` contains every page of the PDF, with page, image, result and
    image_sha256. Model inference is managed separately and never trusted here.
    """
    if figure_cmd and not figure_revision:
        raise ValueError("quality figure reader requires an immutable model/runner revision")
    if type(rectify_labels) is not bool or (rectify_labels and not label_detector_model_dir):
        raise ValueError('label rectification requires a local text detector')
    input_path = Path(input_path).resolve()
    if detect_file_type(input_path) != "pdf":
        raise ValueError("quality import expects the original source PDF")
    info = validate_input(input_path, "pdf", InputLimits())
    source_sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
    out_dir = Path(out_dir).resolve()
    work = out_dir / "work" / "quality"
    work.mkdir(parents=True, exist_ok=True)
    markers, images = {}, {}
    for item in page_results:
        page_id = item["page"]
        if type(page_id) is not int or page_id < 1 or page_id in markers:
            raise ValueError("quality pages must be unique positive integers")
        image = Path(item["image"]).resolve()
        if hashlib.sha256(image.read_bytes()).hexdigest() != item["image_sha256"]:
            raise ValueError("quality source image hash mismatch")
        result = Path(item["result"])
        if result.stat().st_size > 16_000_000:
            raise ValueError("quality page result exceeds byte limit")
        marker = paddle_to_marker(json.loads(result.read_text("utf-8")), image, page_id=page_id, revision=revision,
            completion_path=item.get("completion"), source_sha256=source_sha256)
        target = work / f"p{page_id:04d}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(marker, ensure_ascii=False), "utf-8")
        temporary.replace(target)
        markers[page_id], images[page_id] = target, image
    if set(markers) != set(range(1, info["pages"] + 1)):
        raise ValueError("quality results must cover every source PDF page")
    region_enricher = None
    label_detector = None
    if structured_regions or label_detector_model_dir:
        from .enrichment import RegionEnricher
        label_reader = None
        if label_detector_model_dir:
            from .label_ocr import PaddleTextDetector, DetectedLabelReader,LabelOptions
            label_detector = PaddleTextDetector(label_detector_model_dir)
            try:
                label_reader = DetectedLabelReader(label_detector, language,LabelOptions(rectify=rectify_labels))
            except Exception:
                label_detector.close()
                raise
        region_enricher = RegionEnricher(language=language, label_reader=label_reader)
    try:
        return run_pipeline(input_path, sorted(markers), markers, images, out_dir,
            language=language, profile="general", figure_cmd=figure_cmd,
            figure_revision=figure_revision, figure_timeout=figure_timeout, region_enricher=region_enricher)
    finally:
        if label_detector:
            label_detector.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--language", default="vie+eng")
    parser.add_argument("--figure-cmd")
    parser.add_argument("--figure-revision")
    parser.add_argument("--figure-timeout", type=int, default=15)
    parser.add_argument("--structured-regions", action="store_true")
    parser.add_argument("--label-detector-model-dir", type=Path)
    parser.add_argument('--rectify-labels',action='store_true')
    args = parser.parse_args()
    result = ingest_quality(args.input, args.out, json.loads(args.manifest.read_text("utf-8"))["pages"],
        revision=args.revision, language=args.language, figure_cmd=args.figure_cmd,
        figure_revision=args.figure_revision, figure_timeout=args.figure_timeout, structured_regions=args.structured_regions,
        label_detector_model_dir=args.label_detector_model_dir,rectify_labels=args.rectify_labels)
    print(json.dumps({"pages": len(result["pages"]), "chunks": len(result["chunks"]),
        "validation_errors": len(result["report"]["output_validation_errors"])}))
    return 1 if result["failed_pages"] or result["report"]["output_validation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
