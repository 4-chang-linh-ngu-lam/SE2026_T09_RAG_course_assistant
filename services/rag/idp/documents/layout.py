import base64
import io
import json
import re
from pathlib import Path

from PIL import Image

from idp.documents.normalize import html_text, normalize_text
from idp.validation.validate import looks_like_caption


def is_reading_alternative(block):
    evidence=block.get('source_evidence') or {}
    return evidence.get('reading_role')=='contextual_alternative' or bool(evidence.get('inline_formula_supplement'))


def load_blocks(marker_json_path: str | Path) -> list[dict]:
    data = json.loads(Path(marker_json_path).read_text(encoding="utf-8"))
    page = data["children"][0]
    blocks = []

    def add(block):
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

    def walk(block):
        btype = block.get("block_type")
        children = block.get("children") or []
        # PictureGroup is a layout wrapper; its Picture/Caption children carry
        # the useful content and must not be dropped.
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
    text = " ".join(b["text"] for b in blocks if b["text"]).lower()
    figure_types = {"Diagram", "Picture", "PictureGroup", "Table"}
    figures = sum(1 for b in blocks if b["block_type"] in figure_types)
    formulas = sum(len(b["latex"]) for b in blocks)
    has_text = bool(text.strip())
    if any(b["block_type"] == "TableOfContents" for b in blocks):
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


def section_level(text: str) -> int:
    t = (text or "").strip()
    if re.match(r"^(§\s*\d+\.?|I{1,3}\.|IV\.|V\.|VI\.|BÀI TẬP)(?=\s|$)", t, re.I):
        return 1
    if re.match(r"^\d+\.\s", t):
        return 2
    if t.isupper():
        return 2
    return 3


def build_sections(blocks: list[dict]) -> list[dict]:
    sections = []
    stack: list[tuple[int, str]] = []
    current_page = None
    for block in blocks:
        if block.get("page") != current_page:
            stack.clear()
            current_page = block.get("page")
        if block["block_type"] != "SectionHeader":
            continue
        title = block["text"] or ""
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
        if block["block_type"] == "SectionHeader":
            title = block["text"] or ""
            level = section_level(title)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        block["section_path"] = [s[1] for s in stack]


def attach_captions(blocks: list[dict], max_distance: float = 180) -> None:
    figures = [b for b in blocks if b["block_type"] in {"Diagram", "Picture", "PictureGroup", "Table"}]
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


def figure_kind(block: dict, page_width: float, page_height: float) -> str:
    bbox = block.get("bbox")
    if not bbox:
        return "decorative"
    w = float(bbox[2]) - float(bbox[0])
    h = float(bbox[3]) - float(bbox[1])
    area_ratio = max(0.0, w * h) / max(1.0, page_width * page_height)
    # A small recognized label can carry an essential unit or axis name. Size
    # alone cannot authorize deleting the provider's visible-text candidate.
    if block.get("caption") or (block.get("text") or "").strip() or block.get("latex") or area_ratio >= 0.02:
        return "content"
    return "decorative"


def parse_toc_entries(
    html_fragment: str,
    profile: str | object | None = "general",
) -> list[dict]:
    import html as html_lib

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


def sort_page_headers(blocks: list[dict], page_width: float) -> None:
    """Order two-column page headers left column then right column.

    Marker emits headers row-major, which interleaves the two columns and
    breaks reading order for exam/cover headers. Header block order fields stay
    unchanged for gold alignment; only the list order used for markdown/chunks
    is adjusted.
    """
    positions = [
        index for index, block in enumerate(blocks)
        if block.get("block_type") == "PageHeader" and block.get("bbox")
    ]
    if len(positions) < 4:
        return
    headers = [blocks[index] for index in positions]
    left, right = [], []
    for block in headers:
        bbox = block["bbox"]
        center = (float(bbox[0]) + float(bbox[2])) / 2
        (left if center < page_width * 0.5 else right).append(block)
    if len(left) < 2 or len(right) < 2:
        return
    ordered = (
        sorted(left, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
        + sorted(right, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
    )
    for index, block in zip(positions, ordered):
        blocks[index] = block
