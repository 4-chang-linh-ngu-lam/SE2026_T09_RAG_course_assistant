"""Check and render the local PDF; visual review is a separate explicit step.

Run from repo root with the host Python containing PyMuPDF. Pass
--visual-review-complete only after actually inspecting the current rendered pages.
"""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import fitz


def normalized(value):
    return " ".join(value.split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-review-complete", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    docs = Path(__file__).resolve().parent
    source = root / "BT3_23001878_VT-033.pdf"
    render = root / "services/core/.venv/pdf-qa"
    render.mkdir(parents=True, exist_ok=True)
    summary = json.loads((docs / "submission.json").read_text(encoding="utf-8"))
    pdf = fitz.open(source)
    assert len(pdf) == 10, "Expected8main pages and2appendices"
    text = [page.get_text() for page in pdf]
    for i in range(8):
        assert f"Nội dung chính {i + 1}/8" in text[i]
    assert "Phụ lục A" in text[8] and "Phụ lục B" in text[9]
    for value in (
        "Mai Huy Hoàng", "23001878", "VT-033", "SE2026-T09", "AI-01",
        summary["baseline_sha"], "Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài làm; tôi đã khai báo việc sử dụng AI.",
    ):
        assert normalized(value) in normalized(text[0]), value
    reflection = (docs / "reflection.md").read_text(encoding="utf-8")
    assert 250 <= len(reflection.split()) <= 350
    assert normalized(reflection) in normalized(text[7])
    assert "Gate tải 120: FAIL" in text[0]
    for i in range(1, 19):
        assert re.search(rf"\bT{i:02}\b", text[2 if i <= 9 else 3])
    links = [link["uri"] for page in pdf for link in page.get_links() if "uri" in link]
    assert {summary["branch_url"], summary["pr_url"], summary["ci_url"]} <= set(links)
    embedded = {}
    for page in pdf:
        for xref, _, _, name, *_ in page.get_fonts(full=True):
            if "Arial" in name:
                embedded[name] = len(pdf.extract_font(xref)[3])
    assert len(embedded) >= 2 and all(embedded.values())
    out_of_bounds = []
    for i, page in enumerate(pdf):
        page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(render / f"page-{i + 1:02}.png")
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, y0, x1, y1 = span["bbox"]
                    if x0 < 0 or y0 < 0 or x1 > page.rect.width or y1 > page.rect.height:
                        out_of_bounds.append({"page": i + 1, "bbox": span["bbox"]})
    assert not out_of_bounds
    result = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "pdf": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "main_pages": 8, "appendix_pages": 2, "total_pages": len(pdf),
        "reflection_words_whitespace": len(reflection.split()),
        "required_cover_text": "PASS", "reflection_not_truncated": "PASS",
        "test_case_ids_01_to_18_unbroken": "PASS", "clickable_uri_count": len(links),
        "verified_branch_pr_ci_links": [summary["branch_url"], summary["pr_url"], summary["ci_url"]],
        "embedded_arial_font_bytes": embedded, "out_of_page_text": out_of_bounds,
        "renderer": "PyMuPDF (Poppler unavailable on host)", "rendered_pages": str(render),
        "visual_review_complete": args.visual_review_complete,
        "reviewer": "Codex, not student/owner approval" if args.visual_review_complete else None,
        "ci_verification_snapshot": summary["verification_sha"],
        "load_gate": "FAIL, retained explicitly in report",
    }
    (docs / "evidence/09-pdf-qa.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
