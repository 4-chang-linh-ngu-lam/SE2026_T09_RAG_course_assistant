"""Cheap per-file/per-page preflight for routing digital vs scanned documents."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PIPELINE_VERSION = "idp-preflight-0.1"


def _pdf_pages(path: Path, pages: list[int] | None) -> list[dict]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    doc = fitz.open(path)
    wanted = pages or list(range(1, doc.page_count + 1))
    out = []
    for page_no in wanted:
        if page_no < 1 or page_no > doc.page_count:
            continue
        page = doc[page_no - 1]
        try:
            data = page.get_text("dict")
        except Exception:
            data = {"blocks": []}
        parts = []
        math_font_spans = 0
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = span.get("text", "")
                    if value:
                        parts.append(value)
                        if re.search(
                            r"CMMI|CMSY|CMEX|Symbol|Math", span.get("font", ""), re.I
                        ):
                            math_font_spans += 1
        text = "".join(parts).strip()
        chars = len(text)
        math_chars = len(re.findall(r"[=+\-×÷^_{}\\√∑∫∞≤≥<>]", text))
        math_ratio = math_chars / chars if chars else 0.0
        letter_ratio = (
            sum(1 for c in text if c.isalpha()) / chars if chars else 0.0
        )
        images = page.get_images(full=True)
        dpis = []
        for img in images:
            w, h = img[2], img[3]
            w_in = page.rect.width / 72
            h_in = page.rect.height / 72
            if w_in > 0 and h_in > 0:
                dpis.append(max(w / w_in, h / h_in))
        max_dpi = max(dpis) if dpis else None

        if chars == 0 and not images:
            route = "blank"
        elif chars >= 40 and letter_ratio >= 0.20:
            route = "digital_text"
        elif chars > 0 and chars < 40:
            route = "mixed_review"
        else:
            route = "scan_quality"

        reasons = []
        if chars == 0 and images:
            reasons.append("no_text_layer")
        if chars > 0 and chars < 40:
            reasons.append("sparse_text_layer")
        if max_dpi is not None and max_dpi < 150:
            reasons.append("low_source_dpi")
        if not text and not images:
            reasons.append("blank_page")
        math_page = (
            chars >= 40
            and math_chars >= 12
            and (math_ratio >= 0.01 or math_font_spans >= 3)
        )
        if math_page:
            reasons.append("math_text_layer")
        out.append({
            "page": page_no,
            "route": route,
            "text_chars": chars,
            "letter_ratio": round(letter_ratio, 4),
            "math_chars": math_chars,
            "math_ratio": round(math_ratio, 4),
            "math_font_spans": math_font_spans,
            "image_count": len(images),
            "max_image_dpi": round(max_dpi, 1) if max_dpi else None,
            "reasons": reasons,
        })
    return out


def preflight(path: str | Path, pages: list[int] | None = None) -> dict:
    source = Path(path).resolve()
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        page_rows = _pdf_pages(source, pages)
        routes = [p["route"] for p in page_rows]
        math_pages = [
            p for p in page_rows if "math_text_layer" in p["reasons"]
        ]
        math_heavy = bool(math_pages) and (
            len(math_pages) / max(1, len(routes)) >= 0.2
            or len(math_pages) >= 3
        )
        if routes and all(r == "digital_text" for r in routes):
            lane = "quality" if math_heavy else "digital"
        elif routes and all(r in {"scan_quality", "blank"} for r in routes):
            lane = "quality"
        elif any(r == "digital_text" for r in routes) and any(r == "scan_quality" for r in routes):
            lane = "mixed_review"
        else:
            lane = "review"
        kind = "pdf"
    elif suffix == ".docx":
        page_rows = []
        routes = []
        math_pages = []
        lane = "digital"
        kind = "docx"
    elif suffix == ".txt":
        page_rows = []
        routes = []
        math_pages = []
        lane = "digital"
        kind = "txt"
    else:
        raise ValueError(f"unsupported file type: {suffix}")

    counts = {key: sum(1 for p in page_rows if p["route"] == key) for key in {
        "digital_text", "scan_quality", "blank", "mixed_review"
    }}
    return {
        "pipeline_version": PIPELINE_VERSION,
        "source": str(source),
        "kind": kind,
        "pages": page_rows,
        "page_count": len(page_rows),
        "route_counts": counts,
        "math_pages": [p["page"] for p in math_pages],
        "recommended_lane": lane,
        "review_required": lane in {"mixed_review", "review"} or any(
            "low_source_dpi" in p["reasons"] or p["reasons"] == ["sparse_text_layer"]
            for p in page_rows
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight document routing")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", help="e.g. 1-20,25")
    args = parser.parse_args()
    from idp.orchestration.cli import parse_pages
    pages = parse_pages(args.pages) if args.pages else None
    result = preflight(args.input, pages)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "recommended_lane": result["recommended_lane"],
        "page_count": result["page_count"],
        "route_counts": result["route_counts"],
        "review_required": result["review_required"],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
