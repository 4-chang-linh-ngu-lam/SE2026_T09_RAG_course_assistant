"""Convert PaddleOCR-VL page results into marker-compatible page JSON.

PaddleOCR-VL exposes layout detection scores but no recognition confidence.
Layout boxes and parsed blocks are separate lists with independent ``order``
values, so scores must be matched by geometry, never by ``block_order``.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from PIL import Image, ImageOps


def prepare_page_image(
    source: str | Path,
    target: str | Path,
    *,
    width: int | None = None,
    height: int | None = None,
) -> Image.Image:
    """Save a page image in the same orientation as the OCR result.

    Phone photos often carry EXIF rotation while Paddle reports coordinates in
    the transposed image. Saving the raw file would clip every block outside
    the unrotated size, so apply EXIF and align to Paddle's reported size.
    """
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    expected = (int(width), int(height)) if width and height else None
    if expected and image.size != expected:
        image = image.resize(expected, Image.Resampling.LANCZOS)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return image


def _bbox_of(value) -> list[float] | None:
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("bbox") or value.get("poly") or value.get("points")
    if not value:
        return None
    if len(value) == 4 and all(isinstance(x, (int, float)) for x in value):
        return [float(x) for x in value]
    xs = [float(v) for v in value[0::2]]
    ys = [float(v) for v in value[1::2]]
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = (
        (a[2] - a[0]) * (a[3] - a[1])
        + (b[2] - b[0]) * (b[3] - b[1])
        - inter
    )
    return inter / max(1e-9, union)


def layout_boxes(data: dict) -> list[tuple[list[float], float]]:
    boxes = []
    for box in (data.get("layout_det_res") or {}).get("boxes", []):
        bbox = _bbox_of(box.get("coordinate") or box.get("bbox"))
        if bbox:
            boxes.append((bbox, float(box.get("score") or 0.0)))
    return boxes


def _layout_score(bbox: list[float], boxes: list[tuple[list[float], float]]) -> float | None:
    best_score = None
    best_iou = 0.0
    for box, score in boxes:
        value = _iou(bbox, box)
        if value > best_iou:
            best_iou, best_score = value, score
    return best_score if best_iou >= 0.8 else None


def _table_html(content: str) -> str:
    html_table = content if "<table" in content.lower() else _md_table_to_html(content)
    return re.sub(
        r"\$([^$]+)\$",
        lambda match: "<math>" + html.escape(match.group(1).strip()) + "</math>",
        html_table,
    )


def _md_table_to_html(md: str) -> str:
    rows = []
    for line in (md or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    out = ["<table>"]
    for row in rows:
        out.append(
            "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def _inline_html(text: str) -> str:
    parts = re.split(r"(\$[^$]+\$)", text or "")
    out = []
    for part in parts:
        if len(part) >= 2 and part.startswith("$") and part.endswith("$"):
            out.append("<math>" + html.escape(part[1:-1]) + "</math>")
        else:
            out.append(html.escape(part).replace("\n", "<br/>"))
    return "<p>" + "".join(out) + "</p>"


def _block_type(label: str) -> str:
    label = (label or "").lower()
    if "table" in label and "caption" not in label:
        return "Table"
    if "formula" in label or "equation" in label:
        return "Equation"
    if "figure" in label or "image" in label or "chart" in label:
        return "Picture"
    if "caption" in label:
        return "Caption"
    if label == "header":
        return "PageHeader"
    if label == "footer":
        return "PageFooter"
    if "title" in label or "section" in label or "heading" in label:
        return "SectionHeader"
    return "Text"


def paddle_result_to_marker(
    raw: dict,
    page_image: str | Path,
    *,
    version: str = "1.6",
    fallback_markdown: str = "",
) -> dict:
    data = raw.get("res", raw) if isinstance(raw, dict) else {}
    width, height = Image.open(page_image).size
    expected = (data.get("width"), data.get("height"))
    if expected[0] and expected[1] and (width, height) != expected:
        raise ValueError(
            "page image size does not match Paddle coordinates: "
            f"{width}x{height} != {expected[0]}x{expected[1]}"
        )
    boxes = layout_boxes(data)
    children = []
    for block in data.get("parsing_res_list") or []:
        bbox = _bbox_of(
            block.get("block_bbox") or block.get("bbox") or block.get("poly")
        )
        if not bbox:
            continue
        if max(bbox) <= 1.5:
            bbox = [
                bbox[0] * width,
                bbox[1] * height,
                bbox[2] * width,
                bbox[3] * height,
            ]
        bbox = [
            max(0.0, min(width, bbox[0])),
            max(0.0, min(height, bbox[1])),
            max(0.0, min(width, bbox[2])),
            max(0.0, min(height, bbox[3])),
        ]
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        label = block.get("block_label") or block.get("label") or ""
        content = block.get("block_content") or block.get("content") or ""
        btype = _block_type(label)
        if btype == "Table":
            table_html = _table_html(content)
            child = {"block_type": "Table", "bbox": bbox, "html": table_html or "<p></p>"}
        elif btype == "Equation":
            latex = content.strip().strip("$").replace("$$", "")
            child = {
                "block_type": "Equation",
                "bbox": bbox,
                "html": "<p><math>" + html.escape(latex) + "</math></p>",
            }
        elif btype == "SectionHeader":
            child = {
                "block_type": "SectionHeader",
                "bbox": bbox,
                "html": "<h2>" + _inline_html(content)[3:-4] + "</h2>",
            }
        elif btype == "Caption":
            child = {"block_type": "Caption", "bbox": bbox, "html": _inline_html(content)}
        elif btype == "Picture":
            child = {"block_type": "Picture", "bbox": bbox, "html": ""}
        elif btype == "PageHeader":
            child = {"block_type": "PageHeader", "bbox": bbox, "html": _inline_html(content)}
        elif btype == "PageFooter":
            child = {"block_type": "PageFooter", "bbox": bbox, "html": _inline_html(content)}
        else:
            child = {"block_type": "Text", "bbox": bbox, "html": _inline_html(content)}
        if "chart" in label.lower():
            child["chart"] = True
        score = _layout_score(bbox, boxes)
        if score is not None:
            child["layout_score"] = score
        children.append(child)

    if not children and fallback_markdown.strip():
        children = [{
            "block_type": "Text",
            "bbox": [0, 0, width, height],
            "html": _inline_html(fallback_markdown),
        }]
    layout_available = any(child.get("layout_score") is not None for child in children)
    return {
        "metadata": {
            "engine": "paddleocr_vl",
            "version": version,
            "kind": "ocr",
            "confidence_available": False,
            "layout_confidence_available": layout_available,
        },
        "children": [{
            "block_type": "Page",
            "bbox": [0, 0, width, height],
            "children": children,
        }],
    }
