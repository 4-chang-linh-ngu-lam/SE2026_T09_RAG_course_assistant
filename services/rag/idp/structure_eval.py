"""Located structure diagnostics. No semantic or production certification."""
from collections import Counter
import unicodedata


def _cell(cell):
    text = " ".join(unicodedata.normalize("NFC", cell.get("text") or "").split())
    return (cell["row"], cell["column"], cell.get("rowspan", 1), cell.get("colspan", 1), text)


def _ratio(n, d):
    return n / d if d else 1.0


def _iou(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / max(1e-9, union)


def evaluate_structure(pages, gold):
    scope, items = set(gold.get("table_pages") or []), gold.get("tables") or []
    predictions = [(pid, b) for pid, p in pages.items() if pid in scope for b in p["blocks"] if b["block_type"] == "Table"]
    complete, used, tp, total_gold = bool(scope) and scope <= set(pages), set(), 0, 0
    total_pred = sum(len(b.get("table_cells") or []) for _, b in predictions)
    for item in items:
        valid = item.get("page") in scope and ("block_id" in item or "order" in item) and "cells" in item
        complete &= valid
        expected = Counter(_cell(c) for c in item.get("cells") or [])
        total_gold += sum(expected.values())
        if not valid:
            continue
        for index, (pid, block) in enumerate(predictions):
            located = block.get("block_id") == item["block_id"] if "block_id" in item else block.get("order") == item["order"]
            if index not in used and pid == item["page"] and located:
                used.add(index)
                tp += sum((Counter(_cell(c) for c in block.get("table_cells") or []) & expected).values())
                break
    precision = (_ratio(tp, total_pred) if total_pred or not total_gold else 0.0) if complete else None
    recall = (_ratio(tp, total_gold) if total_gold or not total_pred else 0.0) if complete else None
    visual_scope, visual_gold = set(gold.get("visual_pages") or []), gold.get("visual_regions") or []
    kinds = {"Equation", "Table", "Picture", "Diagram", "Chart", "PictureGroup"}
    visuals = [(pid, b) for pid, p in pages.items() if pid in visual_scope for b in p["blocks"] if b["block_type"] in kinds and b.get("bbox")]
    vcomplete, matched = bool(visual_scope) and visual_scope <= set(pages), set()
    for item in visual_gold:
        valid = item.get("page") in visual_scope and len(item.get("bbox") or []) == 4 and item.get("kind") in kinds
        vcomplete &= valid
        if not valid:
            continue
        choices = [(i, _iou(b["bbox"], item["bbox"])) for i, (pid, b) in enumerate(visuals) if i not in matched and pid == item["page"] and b["block_type"] == item["kind"]]
        if choices:
            index, overlap = max(choices, key=lambda x: x[1])
            if overlap >= .5:
                matched.add(index)
    vp = (_ratio(len(matched), len(visuals)) if visuals or not visual_gold else 0.0) if vcomplete else None
    vr = (_ratio(len(matched), len(visual_gold)) if visual_gold or not visuals else 0.0) if vcomplete else None
    return {
        "diagnostics_only": True, "certifies_production": False,
        "tables": {"gold_complete": complete, "pages": sorted(scope), "cell_exact_precision": precision, "cell_exact_recall": recall, "matched_cells": tp, "predicted_cells": total_pred, "gold_cells": total_gold, "header_accuracy": None, "teds": None},
        "visual_regions": {"gold_complete": vcomplete, "pages": sorted(visual_scope), "precision": vp, "recall": vr, "iou_min": .5, "matching": "greedy_one_to_one", "semantic_accuracy": None},
    }
