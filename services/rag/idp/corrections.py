import json
from pathlib import Path

from .normalize import normalize_latex, normalize_text
from .validate import validate_latex


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
            block["latex_validation"] = [
                validate_latex(x).as_dict() for x in block["latex"]
            ]
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
