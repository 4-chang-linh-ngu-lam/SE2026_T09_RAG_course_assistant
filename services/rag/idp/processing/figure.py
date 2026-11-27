"""Figure, caption, section hierarchy, and visual-evidence utilities."""

from __future__ import annotations

import base64
import html as html_lib
import io
import json
import re
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from idp.processing.formula import html_text, looks_like_caption, normalize_text


def is_reading_alternative(block: dict) -> bool:
    evidence = block.get("source_evidence") or {}
    return evidence.get("reading_role") == "contextual_alternative" or bool(evidence.get("inline_formula_supplement"))


def load_blocks(marker_json_path: str | Path) -> list[dict]:
    data = json.loads(Path(marker_json_path).read_text(encoding="utf-8"))
    page = data["children"][0]
    blocks = []

    def add(block: dict) -> None:
        text, maths = html_text(block.get("html") or "")
        confidence = block.get("confidence")
        if confidence is None:
            confidence = block.get("_idp_confidence")
            if confidence is not None:
                confidence = float(confidence) / 100.0
        elif float(confidence) > 1:
            confidence = float(confidence) / 100.0
        blocks.append({
            "order": len(blocks),
            "block_type": block.get("block_type") or "Unknown",
            "bbox": block.get("bbox"),
            "html": block.get("html") or "",
            "text": text,
            "latex": maths,
            "images": block.get("images") or {},
            "section_hierarchy": block.get("section_hierarchy") or {},
            "layout_score": block.get("layout_score") or block.get("score"),
            "confidence": confidence,
            "recovery_region_id": block.get("recovery_region_id"),
            "chart": bool(block.get("chart")),
            "engine": block.get("engine"),
            "provider_review_flags": block.get("provider_review_flags") or [],
            "source_evidence": block.get("source_evidence"),
            "excluded_from_content": bool(block.get("excluded_from_content")),
        })

    def walk(block: dict) -> None:
        btype = block.get("block_type")
        children = block.get("children") or []
        if btype == "PictureGroup" and children:
            for child in children:
                walk(child)
            return
        if btype in {"Document", "Page"}:
            for child in children:
                walk(child)
            return
        add(block)

    for child in page.get("children") or []:
        walk(child)
    return blocks


def decode_images(images: dict, out_dir: Path, prefix: str) -> list[str]:
    saved = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, encoded in images.items():
        try:
            raw = base64.b64decode(encoded)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).split("/")[-1])
            path = out_dir / f"{prefix}_{safe}.jpg"
            image.save(path, "JPEG", quality=95)
            saved.append(str(path))
        except Exception:
            continue
    return saved


def crop_bbox(page_image: Image.Image, bbox, out_path: Path, padding: int = 8) -> str | None:
    if not bbox:
        return None
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(page_image.width, x2 + padding)
    y2 = min(page_image.height, y2 + padding)
    if x2 <= x1 or y2 <= y1:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_image.crop((x1, y1, x2, y2)).save(out_path, "JPEG", quality=95)
    return str(out_path)


def classify_page(blocks: list[dict]) -> dict:
    text = " ".join(b.get("text") or "" for b in blocks if b.get("text")).lower()
    figure_types = {"Diagram", "Picture", "PictureGroup", "Table"}
    figures = sum(1 for b in blocks if b.get("block_type") in figure_types)
    formulas = sum(len(b.get("latex") or []) for b in blocks)
    has_text = bool(text.strip())
    if any(b.get("block_type") == "TableOfContents" for b in blocks):
        page_type = "toc"
    elif "mục lục" in text:
        page_type = "toc"
    elif "bài tập" in text and figures >= 1:
        page_type = "exercise_figure"
    elif "bài tập" in text:
        page_type = "exercise"
    elif figures >= 3:
        page_type = "figure_heavy"
    elif not has_text and not figures:
        page_type = "blank"
    elif not has_text and figures:
        page_type = "cover_or_image"
    else:
        page_type = "content"
    return {
        "page_type": page_type,
        "has_text": has_text,
        "figure_count": figures,
        "formula_count": formulas,
    }


_SOLUTION_LABEL_RE = re.compile(
    r"^(?:gi[aảàá]i|lời\s+giải|hướng\s+dẫn\s+giải|đáp\s+án|solution|proof|chứng\s+minh)(?:[\s.:!?]*$)",
    re.IGNORECASE,
)
_CALLOUT_LABEL_RE = re.compile(
    r"^(?:(?:ví\s*dụ|vi\s*du)(?:\b|[a-zà-ỹ0-9](?=\s|$))|"
    r"(?:example|luyện\s*tập|luyen\s*tap|vận\s*dụng|van\s*dung|hoạt\s*động|khám\s*phá|"
    r"trải\s*nghiệm|thảo\s*luận|em\s*có\s*biết|chú\s*ý|nhận\s*xét|ghi\s*nhớ|"
    r"thuật\s*ngữ|kiến\s*thức,?\s*k[ĩi]\s*năng)\b)",
    re.IGNORECASE,
)
_NEW_HEADING_PREFIX_RE = re.compile(
    r"^(?:(?i:CHƯƠNG|PHẦN|MỤC|BÀI|ĐIỀU)|\d+\.|[a-z]\.|[IVX]+\.)(?:\s|$)"
)


def section_level(text: str) -> int:
    t = (text or "").strip()
    if re.match(r"^(§\s*\d+\.?|I{1,3}\.|IV\.|V\.|VI\.|CHƯƠNG\s+[IVX\d]+|BÀI\s+\d+|BÀI TẬP)(?=\s|$)", t, re.I):
        return 1
    if re.match(r"^\d+\.\s", t):
        return 2
    if t.isupper():
        return 2
    return 3


def is_structural_section_header(text: str) -> bool:
    """Reject textbook solution/example/callout micro-labels from SectionHeader promotion."""
    t = (text or "").strip()
    if not t or len(t) > 140 or sum(ch.isalnum() for ch in t) < 3:
        return False
    cleaned = re.sub(r"^[^\wÀ-ỹ]+", "", t, flags=re.UNICODE).strip()
    cleaned = re.sub(r"^[a-z]\s+(?=[A-ZÀ-Ỹ])", "", cleaned)
    if not cleaned:
        return False
    if _SOLUTION_LABEL_RE.match(cleaned) or _CALLOUT_LABEL_RE.match(cleaned):
        return False
    return True


def merge_adjacent_section_headers(blocks: list[dict]) -> list[dict]:
    """Coalesce multi-line display titles into a single SectionHeader block."""
    merged: list[dict] = []
    for block in blocks:
        if (
            merged
            and merged[-1].get("block_type") == "SectionHeader"
            and block.get("block_type") == "SectionHeader"
            and merged[-1].get("page") == block.get("page")
        ):
            prev = merged[-1]
            b1, b2 = prev.get("bbox"), block.get("bbox")
            if b1 and b2 and len(b1) == 4 and len(b2) == 4:
                h1 = max(1.0, float(b1[3]) - float(b1[1]))
                h2 = max(1.0, float(b2[3]) - float(b2[1]))
                w1 = max(1.0, float(b1[2]) - float(b1[0]))
                w2 = max(1.0, float(b2[2]) - float(b2[0]))
                v_gap = float(b2[1]) - float(b1[3])
                x_overlap = max(0.0, min(float(b1[2]), float(b2[2])) - max(float(b1[0]), float(b2[0])))
                c1 = (float(b1[0]) + float(b1[2])) * 0.5
                c2 = (float(b2[0]) + float(b2[2])) * 0.5
                t1 = (prev.get("text") or "").strip()
                t2 = (block.get("text") or "").strip()
                if (
                    -2.0 <= v_gap <= max(18.0, 1.4 * max(h1, h2))
                    and (x_overlap / min(w1, w2) >= 0.25 or abs(c1 - c2) <= 0.25 * max(w1, w2))
                    and t1
                    and t2
                    and len(t1) + 1 + len(t2) <= 180
                    and not _NEW_HEADING_PREFIX_RE.match(t2)
                ):
                    merged_text = f"{t1} {t2}"
                    prev["text"] = merged_text
                    prev["bbox"] = [
                        min(float(b1[0]), float(b2[0])),
                        min(float(b1[1]), float(b2[1])),
                        max(float(b1[2]), float(b2[2])),
                        max(float(b1[3]), float(b2[3])),
                    ]
                    prev["markdown"] = f"{'#' * min(6, section_level(merged_text))} {merged_text}"
                    confs = [c for c in (prev.get("confidence"), block.get("confidence")) if c is not None]
                    if confs:
                        prev["confidence"] = min(confs)
                    seen_flags = {(f.get("code"), f.get("severity")) for f in prev.get("review_flags") or []}
                    for fl in block.get("review_flags") or []:
                        sig = (fl.get("code"), fl.get("severity"))
                        if sig not in seen_flags:
                            copied = dict(fl)
                            if prev.get("block_id") and "block_id" in copied:
                                copied["block_id"] = prev["block_id"]
                            prev.setdefault("review_flags", []).append(copied)
                            seen_flags.add(sig)
                    for ap in block.get("asset_paths") or []:
                        if ap not in prev.setdefault("asset_paths", []):
                            prev["asset_paths"].append(ap)
                    continue
        merged.append(block)
    return merged


def build_sections(blocks: list[dict]) -> list[dict]:
    sections = []
    stack: list[tuple[int, str]] = []
    current_page = None
    for block in blocks:
        if block.get("page") != current_page:
            stack.clear()
            current_page = block.get("page")
        if block.get("block_type") != "SectionHeader":
            continue
        title = block.get("text") or ""
        level = section_level(title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        sections.append({
            "page": block.get("page"),
            "order": block["order"],
            "level": level,
            "title": title,
            "path": [s[1] for s in stack],
            "bbox": block["bbox"],
        })
    return sections


def assign_section_paths(blocks: list[dict]) -> None:
    stack: list[tuple[int, str]] = []
    current_page = None
    for block in blocks:
        if block.get("page") != current_page:
            stack.clear()
            current_page = block.get("page")
        if block.get("block_type") == "SectionHeader":
            title = block.get("text") or ""
            level = section_level(title)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        block["section_path"] = [s[1] for s in stack]


def attach_captions(blocks: list[dict], max_distance: float = 180) -> None:
    figures = [b for b in blocks if b.get("block_type") in {"Diagram", "Picture", "PictureGroup", "Table"}]
    captions = [b for b in blocks if looks_like_caption(b.get("text", ""))]
    for fig in figures:
        fb = fig.get("bbox")
        if not fb:
            continue
        fx1, fy1, fx2, fy2 = [float(v) for v in fb]
        fcx = (fx1 + fx2) / 2
        fw = fx2 - fx1
        best = None
        best_score = 1e9
        best_dist = None
        for cap in captions:
            cb = cap.get("bbox")
            if not cb or cap.get("order") == fig.get("order"):
                continue
            cx1, cy1, cx2, cy2 = [float(v) for v in cb]
            ccx = (cx1 + cx2) / 2
            dx = abs(ccx - fcx)
            if cy1 >= fy1 - 30:
                dy = abs(cy1 - fy2)
            else:
                dy = abs(fy1 - cy2) + 20
            if dy > max_distance or dx > max(260, fw * 0.8):
                continue
            score = dy + 0.25 * dx
            if score < best_score:
                best, best_score, best_dist = cap, score, dy
        fig["caption"] = (best.get("text") if best else "") or ""
        fig["caption_block_order"] = best.get("order") if best else None
        fig["caption_distance"] = round(best_dist, 1) if best_dist is not None else None


def prepare_page_figures(page: dict, out_dir: Path) -> None:
    """Associate short, spatially adjacent caption lines and link figure assets."""
    width, height = page.get("page_size") or (0, 0)
    if width <= 0 or height <= 0:
        return
    blocks = [b for b in page["blocks"] if b.get("bbox") and not b.get("excluded_from_content")]
    figures = [b for b in blocks if b["block_type"] in {"Picture", "PictureGroup", "Diagram", "Chart"}]
    captions = [
        b for b in blocks
        if b["block_type"] in {"Text", "Caption"}
        and len((b.get("text") or "").strip()) <= 180
        and re.match(r"^H[ìi]nh\s+(?:[A-Z]\.\s*)?\d+(?:\.\d+)*[a-z]?\b", (b.get("text") or "").strip(), re.I)
    ]
    candidates = []
    for figure in figures:
        if figure.get("caption"):
            continue
        fx1, fy1, fx2, fy2 = figure["bbox"]
        for caption in captions:
            cx1, cy1, cx2, cy2 = caption["bbox"]
            horizontal_overlap = min(fx2, cx2) - max(fx1, cx1)
            if horizontal_overlap < 0.5 * min(fx2 - fx1, cx2 - cx1):
                continue
            if cy1 >= fy2 - 0.004 * height:
                gap = max(0, cy1 - fy2)
            elif cy2 <= fy1 + 0.004 * height:
                gap = max(0, fy1 - cy2) + 0.025 * height
            else:
                continue
            if gap <= 0.075 * height:
                score = gap + 0.12 * abs((cx1 + cx2 - fx1 - fx2) / 2)
                candidates.append((score, figure, caption))
    used_captions = set()
    for _, figure, caption in sorted(candidates, key=lambda item: item[0]):
        key = caption["block_id"]
        if figure.get("caption") or key in used_captions:
            continue
        figure["caption"] = caption["text"].strip()
        figure["caption_block_order"] = caption.get("order")
        figure["review_flags"] = [
            flag for flag in figure.get("review_flags") or []
            if flag.get("code") != "FIGURE_NO_CAPTION"
        ]
        used_captions.add(key)
    root = out_dir.resolve()
    for figure in figures:
        paths = figure.get("asset_paths") or []
        markdown = figure.get("markdown") or ""
        if not paths or (markdown and not markdown.startswith("![](")):
            continue
        try:
            relative = Path(paths[0]).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        alt = (figure.get("caption") or "").replace("\n", " ").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        figure["markdown"] = f"![{alt}](../{quote(relative, safe='/')})"


def figure_kind(block: dict, page_width: float, page_height: float) -> str:
    bbox = block.get("bbox")
    if not bbox:
        return "decorative"
    w = float(bbox[2]) - float(bbox[0])
    h = float(bbox[3]) - float(bbox[1])
    area_ratio = max(0.0, w * h) / max(1.0, page_width * page_height)
    if block.get("caption") or (block.get("text") or "").strip() or block.get("latex") or area_ratio >= 0.02:
        return "content"
    return "decorative"


def parse_toc_entries(html_fragment: str, profile: str | object | None = "general") -> list[dict]:
    entries = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_fragment or "", re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) < 2:
            continue
        title = html_lib.unescape(re.sub(r"<[^>]+>", " ", cells[0]))
        title, _ = normalize_text(title, profile)
        page_match = re.search(r"\d+", html_lib.unescape(re.sub(r"<[^>]+>", " ", cells[1])))
        if title and page_match:
            entries.append({"title": title, "page": int(page_match.group(0))})
    return entries


def visual_evidence(page: dict, block: dict) -> dict | None:
    if block.get("block_type", block.get("type")) not in {"Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"} and not block.get("latex"):
        return None
    image = block.get("block_crop_path") or block.get("crop_path") or next(iter(block.get("asset_paths") or []), None)
    return {
        "page_id": page.get("page_id"),
        "block_id": block.get("block_id"),
        "kind": block.get("block_type", block.get("type")),
        "bbox": block.get("bbox"),
        "image_path": image,
        "page_image": page.get("page_image"),
        "image_sha256": block.get("crop_sha256"),
        "source_image_sha256": page.get("source_image_sha256"),
        "pixel_bbox": block.get("pixel_bbox"),
        "page_image_size": (page.get("structured_enrichment") or {}).get("image_size"),
        "related_block_ids": block.get("related_block_ids") or [],
        "context_relation": "spatial_nearby",
        "context_blocks": [
            {"block_id": b["block_id"], "text": (b.get("text") or "")[:800], "bbox": b.get("bbox")}
            for b in page.get("blocks") or []
            if b["block_id"] in (block.get("related_block_ids") or [])
        ],
        "caption": block.get("caption"),
        "description": block.get("description"),
        "figure_description_provenance": block.get("figure_description_provenance"),
        "visual_facts": block.get("visual_facts"),
        "extraction_status": block.get("structured_status"),
    }


def intersection_ratio(a, b) -> float:
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return inter / max(1, max((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def nested_figure(a, b) -> bool:
    smaller, larger = sorted([(a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])])
    ratio = smaller / max(1.0, larger)
    return ratio >= 0.5 and intersection_ratio(a, b) >= 0.97 * ratio


def related_blocks(page: dict, target: dict) -> list[str]:
    box = target["bbox"]
    candidates = []
    for block in page["blocks"]:
        if block["block_id"] == target["block_id"] or not block.get("bbox"):
            continue
        b = block["bbox"]
        if block["block_type"] in {"Text", "Caption", "SectionHeader"} and min(b[2], box[2]) > max(b[0], box[0]):
            distance = max(0, box[1] - b[3], b[1] - box[3])
            if distance <= max(30, 0.12 * (page.get("page_size") or [0, 500])[1]):
                candidates.append((distance, block["block_id"]))
    return [bid for _, bid in sorted(candidates)[:6]]
