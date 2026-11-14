import argparse
import json
import sys
from pathlib import Path


def _load_pages(out_dir: Path) -> dict[int, dict]:
    pages = {}
    for path in sorted((out_dir / "pages").glob("p*.json")):
        if path.name.endswith("_preprocess.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        pages[data["page_id"]] = data
    return pages


def audit(out_dir: str | Path, expected_pages: list[int] | None = None) -> dict:
    out_dir = Path(out_dir)
    pages = _load_pages(out_dir)
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    chunks = [
        json.loads(line)
        for line in (out_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary_path = out_dir / "batch_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    status_rows = []
    status_path = out_dir / "batch_status.jsonl"
    if status_path.exists():
        status_rows = [
            json.loads(line)
            for line in status_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    if expected_pages is None:
        expected_pages = manifest.get("pages_requested") or list(pages)
    expected = set(int(x) for x in expected_pages)
    missing_pages = sorted(expected - set(pages))
    latest_status = {}
    for row in status_rows:
        latest_status[int(row["page"])] = row
    failed_status = [p for p, row in latest_status.items() if row.get("status") != "ok"]
    # Pipeline manifest belongs to the current conversion. A previous attempt's
    # batch summary is still present while the worker computes this audit.
    failed_summary = [] if latest_status else manifest.get("failed_pages", summary.get("failed", []))

    block_ids = [b["block_id"] for p in pages.values() for b in p["blocks"]]
    duplicate_blocks = sorted({x for x in block_ids if block_ids.count(x) > 1})
    missing_crops = [
        b["block_id"] for p in pages.values() for b in p["blocks"]
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
    content_figures = [
        b for p in pages.values() for b in p["blocks"] if b.get("figure_kind") == "content"
    ]
    covered_figures = [
        b for b in content_figures
        if b.get("caption") or any(f["code"] == "FIGURE_NO_CAPTION" for f in b.get("review_flags", []))
    ]
    review_pages = {
        p["page_id"] for p in pages.values()
        if any(f.get("severity") in {"warning", "error"} for b in p["blocks"] for f in b.get("review_flags", []))
        or any(f.get("severity") in {"warning", "error"} for f in p.get("review", []))
    }
    review_pages.update(
        item["page_id"]
        for item in (report.get("ingestion_quality") or {}).get("page_quality", [])
        if not item.get("auto_publish") and item.get("status") != "blank"
    )
    auto_pages = sorted(set(pages) - review_pages)
    text_chunks = [c for c in chunks if c.get("content_kind") == "text"]
    auto_text = [c for c in text_chunks if not (set(c.get("pages", [])) & review_pages)]
    auto_text_review = [c for c in auto_text if c.get("review_required")]
    review_without_crop = [
        r for r in _load_review(out_dir)
        if r.get("block_id") and not r.get("block_crop_path")
    ]
    empty_pages = sorted(
        p["page_id"] for p in pages.values()
        if not p["blocks"] and p.get("processing_status") != "blank"
    )
    layout_failed_pages = sorted(
        p["page_id"] for p in pages.values()
        if p.get("processing_status") == "layout_failed"
    )
    fast_pages = sorted(
        p["page_id"] for p in pages.values()
        if any(f.get("code") == "FAST_MODE_REVIEW" for f in p.get("review", []))
    )
    fallback_pages = sorted(
        p["page_id"] for p in pages.values()
        if any(f.get("code") == "FALLBACK_ENGINE_REVIEW" for f in p.get("review", []))
    )
    empty_text_blocks = [
        b["block_id"] for p in pages.values() for b in p["blocks"]
        if b["block_type"] in {"Text", "SectionHeader", "PageHeader", "Equation"}
        and b.get("bbox")
        and not (b.get("text") or "").strip()
        and not b.get("latex")
        and not b.get("excluded_from_content")
        and not any(
            f.get("code") in {
                "EMPTY_BLOCK", "EMPTY_BLOCK_RECOVERED",
                "EMPTY_BLOCK_LOW_CONFIDENCE",
            }
            for f in b.get("review_flags", [])
        )
    ]

    checks = {
        "all_expected_pages": {"value": len(missing_pages), "pass": not missing_pages},
        "no_failed_pages": {"value": failed_summary or failed_status, "pass": not failed_summary and not failed_status},
        "pages_have_content": {"value": len(empty_pages), "pass": not empty_pages},
        "no_layout_failed_pages": {
            "value": len(layout_failed_pages), "pass": not layout_failed_pages
        },
        "fast_pages_are_review_only": {
            "value": fast_pages,
            "pass": all(
                c.get("review_required")
                for c in chunks
                if set(c.get("pages", [])) & set(fast_pages)
            ),
        },
        "fallback_pages_are_review_only": {
            "value": fallback_pages,
            "pass": all(
                c.get("review_required")
                for c in chunks
                if set(c.get("pages", [])) & set(fallback_pages)
            ),
        },
        "no_unflagged_empty_blocks": {
            "value": empty_text_blocks,
            "pass": not empty_text_blocks,
        },
        "no_duplicate_blocks": {"value": duplicate_blocks, "pass": not duplicate_blocks},
        "all_blocks_cropped": {"value": len(missing_crops), "pass": not missing_crops},
        "formulas_valid_or_flagged": {"value": len(unflagged_invalid_formulas), "pass": not unflagged_invalid_formulas},
        "figure_coverage": {
            "value": round(len(covered_figures) / max(1, len(content_figures)), 4),
            "pass": len(covered_figures) == len(content_figures),
        },
        "output_validation": {
            "value": len(report.get("output_validation_errors", [])),
            "pass": not report.get("output_validation_errors"),
        },
        "auto_text_review_rate": {
            "value": round(len(auto_text_review) / max(1, len(auto_text)), 4),
            "pass": len(auto_text_review) / max(1, len(auto_text)) <= 0.10,
        },
        "review_items_have_crops": {"value": len(review_without_crop), "pass": not review_without_crop},
    }
    # Re-read current exports. A green report from the writer cannot attest
    # chunk metadata/content that has changed since that report was produced.
    from .validate_output import validate_outputs
    from .export_audit import audit_chunk_export
    current_errors=validate_outputs(out_dir,list(pages.values()),chunks)
    checks['current_output_validation']={'value':current_errors,'pass':not current_errors}
    ingestion_only=manifest.get('ingestion_only')
    if ingestion_only is None:
        ingestion_only=not chunks and report.get('export_audit') is None and report.get('export_pass') is None
    if not ingestion_only:
        current_export=audit_chunk_export(list(pages.values()),chunks)
        checks['current_export_conservation']={'value':current_export['failures'],'pass':current_export['pass']}
    hybrid_identity = manifest.get("structured_enrichment") or {}
    if hybrid_identity.get("runner") == "idp-hybrid-runtime-1" or any(p.get("hybrid_source") for p in pages.values()):
        from .hybrid_runtime import verify_hybrid_page
        hybrid_errors = []
        try:
            canonical = json.loads((out_dir / "canonical.json").read_bytes())
            canonical_pages = {p["page_id"]: p for p in canonical["pages"]}
        except (OSError, ValueError, KeyError, TypeError):
            canonical_pages = {}
        for page_id, page in pages.items():
            try:
                if page["hybrid_source"]["producer"] != hybrid_identity:
                    raise ValueError("hybrid manifest producer mismatch")
                verify_hybrid_page(page, source_sha256=manifest["source_sha256"], image_path=page["page_image"])
                canonical_page = canonical_pages[page_id]
                if canonical_page["hybrid_source"] != page["hybrid_source"]:
                    raise ValueError("canonical hybrid evidence mismatch")
                verify_hybrid_page(canonical_page, source_sha256=manifest["source_sha256"], image_path=page["page_image"])
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                hybrid_errors.append(page_id)
        checks["hybrid_completion_and_payload"] = {"value": hybrid_errors, "pass": not hybrid_errors}
    result = {
        "out_dir": str(out_dir),
        "pages": len(pages),
        "expected_pages": sorted(expected),
        "missing_pages": missing_pages,
        "failed_pages": failed_summary or failed_status,
        "review_pages": sorted(review_pages),
        "layout_failed_pages": layout_failed_pages,
        "fast_pages": fast_pages,
        "fallback_pages": fallback_pages,
        "empty_text_blocks": empty_text_blocks,
        "auto_pages": auto_pages,
        "content_figures": len(content_figures),
        "content_figures_covered": len(covered_figures),
        "formulas": sum(len(b.get("latex") or []) for p in pages.values() for b in p["blocks"]),
        "chunks": len(chunks),
        "publishable_chunks": sum(1 for c in chunks if c.get("publishable")),
        "review_required_chunks": sum(1 for c in chunks if c.get("review_required")),
        "toc_entries": len(json.loads((out_dir / "document.json").read_text(encoding="utf-8")).get("toc", [])),
        "checks": checks,
        "pass": all(c["pass"] for c in checks.values()),
    }
    (out_dir / "audit_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


def _load_review(out_dir: Path) -> list[dict]:
    path = out_dir / "review_queue.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", help="expected page range, e.g. 1-130")
    args = parser.parse_args()
    expected = None
    if args.pages:
        from .cli import parse_pages
        expected = parse_pages(args.pages)
    result = audit(args.out, expected)
    print(json.dumps({
        "pass": result["pass"],
        "pages": result["pages"],
        "review_pages": result["review_pages"],
        "checks": result["checks"],
    }, ensure_ascii=False, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
