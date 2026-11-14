import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from .structure_eval import evaluate_structure

DEFAULT_GATES = {
    "text_cer_max": 0.005,
    "text_wer_max": 0.02,
    "formula_exact_min": 0.95,
    "figure_coverage_min": 1.0,
    "text_review_rate_max": 0.10,
}


def _words(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s or "")
    # Case, signs, decimal separators, charges and units carry meaning in STEM.
    return re.findall(r"\w+|[^\w\s]", s, re.UNICODE)


def _evaluation_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _lev(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cer(pred: str, gold: str) -> float:
    return _lev(_evaluation_text(pred), _evaluation_text(gold)) / max(1, len(_evaluation_text(gold)))


def _wer(pred: str, gold: str) -> float:
    return _lev(_words(pred), _words(gold)) / max(1, len(_words(gold)))


def _load_pages(out_dir: Path) -> dict[int, dict]:
    pages = {}
    for path in sorted((out_dir / "pages").glob("p*.json")):
        if path.name.endswith("_preprocess.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        pages[data["page_id"]] = data
    return pages


def _formula_key(latex: str) -> str:
    # Formatting whitespace only: do not lowercase symbols, remove grouping,
    # or conflate decimal points and multiplication as legacy evaluation did.
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", latex or ""))


def _evaluate_formulas(pages: dict[int, dict], gold: dict) -> dict:
    predictions = [
        {"page": page_id, "order": block.get("order"),
         "block_id": block.get("block_id"), "latex": latex}
        for page_id, page in pages.items() for block in page["blocks"]
        for latex in block.get("latex") or []
    ]
    # These pages must be fully annotated, including pages with zero formulas.
    scope = {int(p) for p in gold.get("formula_pages", [])}
    used = set()
    items = []
    complete = bool(scope) and scope <= set(pages)
    for item in gold.get("formulas", []):
        located = "page" in item and ("order" in item or "block_id" in item)
        page = int(item["page"]) if located else None
        if not located or page not in scope:
            complete = False
        matched = None
        if located:
            for index, pred in enumerate(predictions):
                if index in used or pred["page"] != page:
                    continue
                if "order" in item and pred["order"] != int(item["order"]):
                    continue
                if "block_id" in item and pred["block_id"] != item["block_id"]:
                    continue
                if _formula_key(pred["latex"]) == _formula_key(item["latex"]):
                    matched = index
                    used.add(index)
                    break
        items.append({**item, "located": located, "matched": matched is not None})
    scoped_predictions = [p for p in predictions if p["page"] in scope]
    true_positives = sum(1 for i in used if predictions[i]["page"] in scope)
    applicable = bool(predictions or items or scope)
    # A legacy document-wide containment score is diagnostic only.
    keys = {_formula_key(p["latex"]) for p in predictions}
    legacy = [i for i in items if not i["located"]]
    return {
        "items": items, "applicable": applicable,
        "gold_complete": complete if applicable else True,
        "recall": sum(i["matched"] for i in items) / len(items) if items else (1.0 if scope else None),
        "precision": true_positives / len(scoped_predictions) if scoped_predictions else (1.0 if scope else None),
        "false_positives": len(scoped_predictions) - true_positives,
        "legacy_containment": (
            sum(_formula_key(i["latex"]) in keys for i in legacy) / len(legacy)
            if legacy else None
        ),
    }


def evaluate(out_dir: str | Path, gold_path: str | Path, gates: dict | None = None) -> dict:
    out_dir = Path(out_dir)
    gates = {**DEFAULT_GATES, **(gates or {})}
    gold_bytes = Path(gold_path).read_bytes()
    gold = json.loads(gold_bytes.decode("utf-8"))
    pages = _load_pages(out_dir)
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    chunks = [
        json.loads(line)
        for line in (out_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    block_by_key = {}
    for page_id, page in pages.items():
        for block in page["blocks"]:
            block_by_key[(page_id, block["order"])] = block

    text_items = []
    for item in gold.get("text", []):
        key = (int(item["page"]), int(item["order"]))
        block = block_by_key.get(key)
        pred = (block or {}).get("text", "")
        gold_text = item["gold"]
        text_items.append({
            **item,
            "prediction": pred,
            "cer": round(_cer(pred, gold_text), 4),
            "wer": round(_wer(pred, gold_text), 4),
            "found": block is not None,
            "char_edits": _lev(_evaluation_text(pred), _evaluation_text(gold_text)),
            "reference_chars": len(_evaluation_text(gold_text)),
            "word_edits": _lev(_words(pred), _words(gold_text)),
            "reference_words": len(_words(gold_text)),
        })
    text_cer = sum(x["char_edits"] for x in text_items) / max(1, sum(x["reference_chars"] for x in text_items))
    text_wer = sum(x["word_edits"] for x in text_items) / max(1, sum(x["reference_words"] for x in text_items))

    formula_eval = _evaluate_formulas(pages, gold)
    formula_items = formula_eval["items"]
    formula_exact = formula_eval["recall"]

    content_figures = [b for p in pages.values() for b in p["blocks"] if b.get("figure_kind") == "content"]
    figure_coverage = (
        sum(
            1 for b in content_figures
            if b.get("caption") or any(f["code"] == "FIGURE_NO_CAPTION" for f in b.get("review_flags", []))
        ) / len(content_figures)
        if content_figures else 1.0
    )

    missing_crops = [
        f"{p['page_id']}:{b['order']}"
        for p in pages.values() for b in p["blocks"]
        if not b.get("excluded_from_content") and not b.get("block_crop_path")
    ]
    invalid_formulas = [
        f"{p['page_id']}:{b['order']}"
        for p in pages.values() for b in p["blocks"]
        for v in b.get("latex_validation", [])
        if not v.get("valid")
    ]
    unflagged_invalid_formulas = [
        f"{p['page_id']}:{b['order']}"
        for p in pages.values() for b in p["blocks"]
        if any(not v.get("valid") for v in b.get("latex_validation", []))
        and not any(
            f.get("severity") in {"warning", "error"}
            for f in b.get("review_flags", [])
        )
    ]
    review_pages = [int(x) for x in gold.get("review_pages", [])]
    review_page_set = set(review_pages)
    math_review_codes = {
        "FORMULA_SEMANTIC_REVIEW", "FORMULA_FRAGMENT",
        "MATH_TEXT_INTEGRITY", "FORMULA_PLACEHOLDER", "FORMULA_ALIGNMENT_REVIEW",
        "LATEX_INVALID", "FORMULA_INCOMPLETE",
        "FORMULA_SIGN_REVIEW", "FORMULA_SIGN_CORRECTED",
        "MISSING_NUMERIC_CONTEXT",
    }
    auto_text_chunks = [
        c for c in chunks
        if c.get("content_kind") == "text"
        and not (set(c.get("pages", [])) & review_page_set)
    ]
    auto_review_chunks = [
        c for c in auto_text_chunks
        if any(f.get("code") not in math_review_codes for f in c.get("review_flags", []))
    ]
    review_rate = (
        len(auto_review_chunks) / len(auto_text_chunks) if auto_text_chunks else 0.0
    )
    empty_pages = report.get("pages_without_content", 0)
    output_errors = report.get("output_validation_errors", [])
    unflagged_review_pages = []
    for page_id in review_pages:
        page = pages.get(page_id)
        if not page:
            unflagged_review_pages.append(page_id)
            continue
        has_review = any(
            f.get("severity") in {"warning", "error"}
            for b in page["blocks"] for f in b.get("review_flags", [])
        ) or any(f.get("severity") in {"warning", "error"} for f in page.get("review", []))
        if not has_review:
            unflagged_review_pages.append(page_id)
    semantic_flag_rate = (
        report.get("formula_semantic_flags", 0) / max(1, report.get("formulas", 1))
    )

    checks = {
        "text_gold_present": {"value": len(text_items), "pass": bool(text_items) and all(_evaluation_text(i["gold"]) for i in text_items)},
        "text_cer": {"value": round(text_cer, 4), "max": gates["text_cer_max"], "pass": text_cer <= gates["text_cer_max"]},
        "text_wer": {"value": round(text_wer, 4), "max": gates["text_wer_max"], "pass": text_wer <= gates["text_wer_max"]},
        "formula_gold_complete": {"value": formula_eval["gold_complete"], "pass": formula_eval["gold_complete"]},
        "formula_exact": {"value": formula_exact, "min": gates["formula_exact_min"], "pass": not formula_eval["applicable"] or (formula_exact is not None and formula_exact >= gates["formula_exact_min"])},
        "formula_precision": {"value": formula_eval["precision"], "min": gates["formula_exact_min"], "pass": not formula_eval["applicable"] or (formula_eval["precision"] is not None and formula_eval["precision"] >= gates["formula_exact_min"])},
        "figure_coverage": {"value": round(figure_coverage, 4), "min": gates["figure_coverage_min"], "pass": figure_coverage >= gates["figure_coverage_min"]},
        "text_review_rate": {"value": round(review_rate, 4), "max": gates["text_review_rate_max"], "pass": review_rate <= gates["text_review_rate_max"]},
        "all_blocks_cropped": {"value": len(missing_crops), "max": 0, "pass": not missing_crops},
        "all_pages_have_content": {"value": empty_pages, "max": 0, "pass": empty_pages == 0},
        "output_validation": {"value": len(output_errors), "max": 0, "pass": not output_errors},
        "review_pages_flagged": {"value": len(unflagged_review_pages), "max": 0, "pass": not unflagged_review_pages},
        "all_formulas_valid_or_flagged": {"value": len(unflagged_invalid_formulas), "max": 0, "pass": not unflagged_invalid_formulas},
    }
    result = {
        "evaluation_version": "idp-eval-2",
        "structured_diagnostics": evaluate_structure(pages, gold),
        "certifies_production": False,
        "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
        "out_dir": str(out_dir),
        "gold": str(gold_path),
        "text_items": text_items,
        "formula_items": formula_items,
        "formula_evaluation": formula_eval,
        "diagnostics": {
            "formula_semantic_flag_rate": semantic_flag_rate,
            "formula_semantic_accuracy": None,
        },
        "report": {
            "pages": report.get("pages"),
            "chunks": report.get("chunks"),
            "publishable_chunks": report.get("publishable_chunks"),
            "review_required_chunks": report.get("review_required_chunks"),
            "content_figures": len(content_figures),
            "missing_crops": missing_crops,
            "invalid_formulas": invalid_formulas,
        },
        "checks": checks,
        "pass": all(c["pass"] for c in checks.values()),
    }
    (out_dir / "gate_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--gold", required=True)
    args = parser.parse_args()
    result = evaluate(args.out, args.gold)
    print(json.dumps({
        "pass": result["pass"],
        "checks": result["checks"],
        "text_cer": result["checks"]["text_cer"]["value"],
        "formula_exact": result["checks"]["formula_exact"]["value"],
        "text_review_rate": result["checks"]["text_review_rate"]["value"],
    }, ensure_ascii=False, indent=1))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
