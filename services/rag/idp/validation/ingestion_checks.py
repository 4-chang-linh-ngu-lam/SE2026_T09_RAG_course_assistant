"""Verify canonical-only ingestion artifacts without downstream chunk/audit modules."""
from __future__ import annotations
import json
from pathlib import Path


def check_ingestion_artifacts(out_dir: str | Path, expected_pages: list[int] | None = None) -> dict:
    out = Path(out_dir)
    errors = []
    try:
        canonical = json.loads((out / "canonical.json").read_text(encoding="utf-8"))
        ingestion = json.loads((out / "ingestion_report.json").read_text(encoding="utf-8"))
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"pass": False, "errors": [f"missing/invalid ingestion artifacts: {exc}"]}
    if not isinstance(canonical, dict) or not isinstance(ingestion, dict) or not isinstance(report, dict):
        return {"pass": False, "errors": ["ingestion artifacts must be JSON objects"]}
    if not canonical.get("schema_version") or not canonical.get("source_sha256"):
        errors.append("canonical schema or source hash missing")
    pages = canonical.get("pages")
    if not isinstance(pages, list):
        errors.append("canonical pages must be a list")
        pages = []
    seen = set()
    for page in pages:
        if not isinstance(page, dict) or type(page.get("page_id")) is not int:
            errors.append("invalid canonical page entry")
            continue
        pid = page["page_id"]
        if pid in seen:
            errors.append(f"duplicate canonical page {pid}")
        seen.add(pid)
        page_file = out / "pages" / f"p{pid:04d}.json"
        if not page_file.is_file():
            errors.append(f"missing parsed page JSON: {pid}")
    if expected_pages is not None and set(expected_pages) != seen:
        errors.append(f"page coverage mismatch: expected {sorted(set(expected_pages))}, got {sorted(seen)}")
    for message in report.get("output_validation_errors") or []:
        errors.append(f"output validation: {message}")
    if canonical.get("failed_pages") or report.get("failed_pages"):
        errors.append("one or more pages failed ingestion")
    if not isinstance(ingestion.get("checks"), dict) or not isinstance(ingestion.get("pass"), bool):
        errors.append("missing canonical ingestion quality checks")
    return {"pass": not errors, "errors": errors, "checked_pages": len(seen),
            "ingestion_pass": ingestion.get("pass")}
