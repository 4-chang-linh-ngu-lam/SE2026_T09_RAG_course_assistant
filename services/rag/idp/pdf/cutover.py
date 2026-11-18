"""Cutover gate: decide from a real shadow corpus whether unified may become default.

Shadow runs (``engine="shadow"``) keep legacy authoritative and write
``shadow_diff.json`` next to each legacy output. This module aggregates those
files and applies an explicit, versioned gate. It never changes the default
engine itself: ``DEFAULT_PDF_ENGINE`` in ``idp.pdf.service`` is changed by a
reviewed commit only after this gate passes on the owner-approved corpus.

The thresholds below are starting values for that review, not measured
acceptance criteria; the owner sets them in ``ShadowGate`` for the run.

Legacy is not ground truth (audit IDP-016): unified intentionally withholds
page furniture and unusable hidden layers, so a lower character ratio can be
an improvement. Version 2 therefore also gates unified's own failed pages and
withheld content, reports latency, and lists every document below the median
character threshold for manual "better/worse" classification. Optional
latency/withheld thresholds stay ``None`` (report only) until the owner sets
them. A labelled golden set is still required before cutover.

    python -m idp.pdf.cutover /data/shadow-runs --min-documents 50
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ShadowGate:
    version: str = "deepdoc-cutover-gate:2"
    min_documents: int = 30
    # Documents with any unified OCR page failure (pages left unread).
    max_failed_page_documents: int = 0
    # Owner-set budgets; None reports the metric without gating on it.
    max_p95_seconds_per_page: float | None = None
    max_median_withheld_ratio: float | None = None
    # Any unified crash on the corpus blocks cutover.
    max_unified_failure_rate: float = 0.0
    # Unified must keep (almost) all legacy published characters on median,
    # and no single document may lose more than ``min_document_char_ratio``.
    min_median_char_ratio: float = 0.97
    min_document_char_ratio: float = 0.80
    # Word 5-gram agreement with legacy (order-insensitive).
    min_median_jaccard: float = 0.90
    # Share of pages unified leaves in review (not published).
    max_median_review_page_ratio: float = 0.05

    def __post_init__(self):
        if self.max_failed_page_documents < 0 or any(
            value is not None and (not math.isfinite(value) or value < 0)
            for value in (self.max_p95_seconds_per_page, self.max_median_withheld_ratio)
        ):
            raise ValueError("invalid cutover gate")
        if self.min_documents < 1 or any(
            not math.isfinite(v) or not 0 <= v <= 1
            for v in (
                self.max_unified_failure_rate,
                self.min_median_char_ratio,
                self.min_document_char_ratio,
                self.min_median_jaccard,
                self.max_median_review_page_ratio,
            )
        ):
            raise ValueError("invalid cutover gate")


def _document(diff):
    if diff.get("schema") != "deepdoc-shadow:1":
        raise ValueError("not a deepdoc shadow comparison")
    if diff.get("status") != "compared":
        return {"source_sha256": diff.get("source_sha256"), "failed": True}
    legacy, unified = diff["legacy"], diff["unified"]
    pages = max(1, unified.get("pages") or 0)
    report = diff.get("unified_report", {})
    review = len(report.get("review_pages", ()))
    publication = report.get("publication") or {}
    return {
        "failed_pages": len(report.get("failed_pages", ())),
        "seconds_per_page": report["seconds"] / pages
        if isinstance(report.get("seconds"), (int, float))
        else None,
        "withheld_ratio": publication.get("withheld_chars_ratio"),
        "source_sha256": diff["source_sha256"],
        "failed": False,
        "char_ratio": unified["characters"] / legacy["characters"]
        if legacy["characters"]
        else 1.0,
        "jaccard": diff.get("shingle_jaccard"),
        "review_page_ratio": review / pages,
        "unified_tables": unified.get("tables", 0),
        "legacy_tables": legacy.get("tables", 0),
    }


def evaluate(diffs, gate=None):
    gate = gate or ShadowGate()
    documents = {}
    for diff in diffs:
        item = _document(diff)
        # One verdict per source; repeated runs of the same PDF do not count twice.
        documents[item["source_sha256"]] = item
    rows = list(documents.values())
    compared = [r for r in rows if not r["failed"]]
    reasons = []
    if len(rows) < gate.min_documents:
        reasons.append(f"CORPUS_TOO_SMALL:{len(rows)}<{gate.min_documents}")
    failure_rate = (len(rows) - len(compared)) / len(rows) if rows else 1.0
    if failure_rate > gate.max_unified_failure_rate:
        reasons.append(f"UNIFIED_FAILURES:{failure_rate:.3f}")
    metrics = {"documents": len(rows), "unified_failure_rate": failure_rate}
    if compared:
        ratios = [r["char_ratio"] for r in compared]
        jaccards = [r["jaccard"] for r in compared if r["jaccard"] is not None]
        reviews = [r["review_page_ratio"] for r in compared]
        metrics.update(
            median_char_ratio=statistics.median(ratios),
            min_char_ratio=min(ratios),
            median_jaccard=statistics.median(jaccards) if jaccards else None,
            median_review_page_ratio=statistics.median(reviews),
            unified_tables=sum(r["unified_tables"] for r in compared),
            legacy_tables=sum(r["legacy_tables"] for r in compared),
        )
        if metrics["median_char_ratio"] < gate.min_median_char_ratio:
            reasons.append("CHARACTER_COVERAGE_REGRESSION")
        lost = [
            r["source_sha256"]
            for r in compared
            if r["char_ratio"] < gate.min_document_char_ratio
        ]
        if lost:
            reasons.append(f"DOCUMENTS_LOSING_TEXT:{len(lost)}")
            metrics["documents_losing_text"] = sorted(lost)
        if not jaccards:
            reasons.append("NO_CONTENT_AGREEMENT_MEASURE")
        elif metrics["median_jaccard"] < gate.min_median_jaccard:
            reasons.append("CONTENT_AGREEMENT_REGRESSION")
        if metrics["median_review_page_ratio"] > gate.max_median_review_page_ratio:
            reasons.append("REVIEW_PAGE_REGRESSION")
        failed = sorted(r["source_sha256"] for r in compared if r["failed_pages"])
        metrics["documents_with_failed_pages"] = failed
        if len(failed) > gate.max_failed_page_documents:
            reasons.append(f"UNIFIED_FAILED_PAGES:{len(failed)}")
        speeds = sorted(
            r["seconds_per_page"] for r in compared if r["seconds_per_page"] is not None
        )
        metrics["p95_seconds_per_page"] = (
            speeds[min(len(speeds) - 1, math.ceil(0.95 * len(speeds)) - 1)]
            if speeds
            else None
        )
        if gate.max_p95_seconds_per_page is not None and (
            metrics["p95_seconds_per_page"] is None
            or metrics["p95_seconds_per_page"] > gate.max_p95_seconds_per_page
        ):
            reasons.append("LATENCY_BUDGET_EXCEEDED")
        withheld = [r["withheld_ratio"] for r in compared if r["withheld_ratio"] is not None]
        metrics["median_withheld_ratio"] = (
            statistics.median(withheld) if withheld else None
        )
        if gate.max_median_withheld_ratio is not None and (
            metrics["median_withheld_ratio"] is None
            or metrics["median_withheld_ratio"] > gate.max_median_withheld_ratio
        ):
            reasons.append("WITHHELD_CONTENT_REGRESSION")
        # Legacy is not ground truth: every document below the median
        # threshold needs a human verdict on whether unified is better or worse.
        metrics["documents_for_manual_review"] = sorted(
            r["source_sha256"]
            for r in compared
            if r["char_ratio"] < gate.min_median_char_ratio
        )
    return {
        "schema": "deepdoc-cutover-report:1",
        "gate": asdict(gate),
        "passed": not reasons,
        "reasons": reasons,
        "metrics": metrics,
    }


def load_diffs(roots):
    for root in roots:
        root = Path(root)
        paths = [root] if root.is_file() else sorted(root.rglob("shadow_diff.json"))
        for path in paths:
            yield json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--min-documents", type=int, default=ShadowGate.min_documents)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = evaluate(load_diffs(args.roots), ShadowGate(min_documents=args.min_documents))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
