"""Check that parsed source content survives the text-retrieval export.

This is a deterministic conservation check, not an OCR accuracy/retrieval score.
It cannot detect content the upstream parser never saw.
"""
from __future__ import annotations

from collections import Counter
import re
import unicodedata
import json

from .structure import parse_table_html

EXPORT_AUDIT_VERSION = "idp-export-audit-2"


def _key(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value or "")).strip()


def audit_chunk_export(pages, chunks):
    linked = {}
    for chunk in chunks:
        for block_id in chunk.get("block_ids", []):
            linked.setdefault(block_id, []).append(chunk)
    headers = Counter(_key(b.get("text")).lower() for p in pages for b in p["blocks"] if b["block_type"] == "PageHeader")
    checks, excluded, empty, missing_visual_text = [], [], [], []
    for page in pages:
        for block in page["blocks"]:
            bid, kind = block["block_id"], block["block_type"]
            reason = None
            if block.get("excluded_from_content"):
                reason = "source_excluded"
            elif kind == "PageFooter":
                reason = "page_footer_policy"
            elif kind == "PageHeader":
                key = _key(block.get("text")).lower()
                if not key or headers[key] >= 3 or re.fullmatch(r"(trang\s*)?\d+", key):
                    reason = "running_header_policy"
            elif kind in {"Picture", "Diagram", "PictureGroup", "Chart"} and block.get("figure_kind") == "decorative" and not block.get("caption"):
                reason = "declared_decorative"
            if reason:
                excluded.append({"page": page["page_id"], "block_id": bid, "reason": reason})
                continue
            owners = linked.get(bid, [])
            actual = _key("\n".join(c.get("text") or "" for c in owners))
            expected = block.get("text") if kind == "Caption" else (block.get("markdown") or block.get("text"))
            payloads = [expected or "", *block.get("latex", [])]
            payloads += [block.get("caption") or "", block.get("description") or ""] if kind in {"Picture", "Diagram", "PictureGroup", "Chart"} else []
            if kind in {"Picture", "Diagram", "PictureGroup", "Chart"}:
                payloads.extend(label.get("text") or "" for label in block.get("visual_labels") or [])
                if block.get("chart_data") is not None:
                    payloads.append(json.dumps(block["chart_data"], ensure_ascii=False))
            if kind == "Table":
                try:
                    source = parse_table_html(block.get("table_html") or block.get("html") or block.get("markdown") or "")
                    expected_cells = Counter(_key(c["text"]) for c in source["cells"] if _key(c["text"]))
                    actual_cells = Counter()
                    for chunk in owners:
                        try:
                            actual_cells.update(_key(c["text"]) for c in parse_table_html(chunk.get("text") or "")["cells"] if _key(c["text"]))
                        except ValueError:
                            pass
                    missing = bool(expected_cells - actual_cells)
                    checks.append({"page": page["page_id"], "block_id": bid, "kind": kind,
                        "pass": bool(owners) and not missing, "reason": "table_cell_text_missing" if missing else None})
                except ValueError:
                    checks.append({"page": page["page_id"], "block_id": bid, "kind": kind,
                        "pass": False, "reason": "source_table_unparseable"})
                continue
            payloads = [_key(x) for x in payloads if _key(x)]
            if not payloads:
                empty.append({"page": page["page_id"], "block_id": bid})
                if kind in {"Picture", "Diagram", "PictureGroup", "Chart"}:
                    missing_visual_text.append({"page": page["page_id"], "block_id": bid})
                continue
            checks.append({"page": page["page_id"], "block_id": bid, "kind": kind,
                "pass": bool(owners) and all(x in actual for x in payloads),
                "reason": "parsed_payload_or_source_reference_missing" if not owners or any(x not in actual for x in payloads) else None})
    failures = [c for c in checks if not c["pass"]]
    return {"version": EXPORT_AUDIT_VERSION, "pass": not failures, "checks": checks,
        "failures": failures, "excluded": excluded, "source_empty": empty,
        "visual_text_missing": missing_visual_text, "certifies_ocr_accuracy": False,
        "certifies_retrieval": False}
