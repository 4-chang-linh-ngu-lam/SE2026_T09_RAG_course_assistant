"""Review item collection, JSONL export, and human-correction helpers."""

from __future__ import annotations

import json
from pathlib import Path

from idp.processing.formula import normalize_latex, normalize_text, validate_latex


def collect_review(pages: list[dict], page_quality: list[dict] | None = None) -> list[dict]:
    review = []
    for page in pages:
        for item in page.get("review", []):
            if item.get("block_id") is None:
                review.append(item)
        for block in page["blocks"]:
            for flag in block.get("review_flags") or []:
                if flag.get("severity") in {"warning", "error"}:
                    review.append({
                        "page": page["page_id"],
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "bbox": block.get("bbox"),
                        "block_crop_path": block.get("block_crop_path"),
                        **flag,
                    })
    for item in page_quality or []:
        if not item.get("publish_authorized") and item.get("status") != "blank":
            review.append({
                "page": item["page_id"],
                "block_id": None,
                "block_type": "Page",
                "bbox": None,
                "code": "PUBLISH_NOT_AUTHORIZED",
                "severity": "warning",
                "reason": "source has no eligible recognition score or explicit trust",
            })
    return review


def write_review_queue(out_dir: Path, review_items: list[dict]) -> Path:
    target = Path(out_dir) / "review_queue.jsonl"
    content = "\n".join(json.dumps(item, ensure_ascii=False) for item in review_items)
    if content:
        content += "\n"
    target.write_text(content, encoding="utf-8")
    return target


def apply_corrections(page_json_path: str | Path, corrections: list[dict]) -> list[dict]:
    path = Path(page_json_path)
    page = json.loads(path.read_text(encoding="utf-8"))
    by_id = {b.get("block_id"): b for b in page["blocks"]}
    by_order = {b.get("order"): b for b in page["blocks"]}
    applied = []
    for corr in corrections:
        block = by_id.get(corr.get("block_id")) or by_order.get(corr.get("order"))
        if block is None:
            continue
        if corr.get("text") is not None:
            text, _ = normalize_text(corr["text"])
            block["text"] = text
            block["markdown"] = text
        if corr.get("markdown") is not None:
            block["markdown"] = corr["markdown"]
        if corr.get("latex") is not None:
            block["latex"] = [normalize_latex(x) for x in corr["latex"]]
            block["latex_validation"] = [validate_latex(x).as_dict() for x in block["latex"]]
        block["review_flags"] = [
            f for f in block.get("review_flags") or []
            if f.get("code") in {"FORMULA_PLACEHOLDER"}
        ]
        block["review_flags"].append({
            "code": "HUMAN_CORRECTED",
            "severity": "info",
            "reviewer": corr.get("reviewer"),
        })
        block["human_corrected"] = True
        applied.append(block["block_id"])
    path.write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")
    return applied
