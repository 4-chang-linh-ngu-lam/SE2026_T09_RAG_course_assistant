import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

from idp.documents.layout import load_blocks
from idp.documents.normalize import html_to_markdown, normalize_latex, normalize_text
from idp.validation.validate import validate_latex

REPAIR_FLAGS = {
    "MATH_TEXT_INTEGRITY",
    "FORMULA_FRAGMENT",
    "FORMULA_SEMANTIC_REVIEW",
    "LATEX_INVALID",
}


def _run_marker_on_crop(
    image_path: Path,
    bbox,
    marker_bin: str,
    llama_bin: str | None,
    work_dir: Path,
    timeout_seconds: int = 120,
) -> dict:
    image = Image.open(image_path).convert("RGB")
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    for pad in (4, 8, 12):
        crop = image.crop((
            max(0, x1 - pad), max(0, y1 - pad),
            min(image.width, x2 + pad), min(image.height, y2 + pad),
        ))
        work_dir.mkdir(parents=True, exist_ok=True)
        crop_path = work_dir / "block.png"
        crop.save(crop_path)
        out_dir = work_dir / "marker"
        out_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.setdefault("SURYA_INFERENCE_BACKEND", "llamacpp")
        if llama_bin:
            env["LLAMA_CPP_BINARY"] = llama_bin
        try:
            subprocess.run(
                [
                    marker_bin, str(crop_path),
                    "--mode", "balanced",
                    "--output_format", "markdown",
                    "--output_dir", str(out_dir),
                    "--disable_multiprocessing",
                ],
                check=True,
                env=env,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            break
        except subprocess.CalledProcessError:
            continue
        md_path = out_dir / "block" / "block.md"
        if not md_path.exists():
            continue
        markdown = md_path.read_text(encoding="utf-8")
        math_re = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
        latex = []
        for match in math_re.finditer(markdown):
            value = match.group(1) or match.group(2) or ""
            if value.strip():
                latex.append(normalize_latex(value))
        if latex:
            return {"markdown": markdown.strip(), "latex": latex}
    return {"markdown": "", "latex": []}


def _split_formula(latex: str) -> list[str]:
    parts = re.split(r"\\text\{\s*(nên|và|hoặc)\s*\}", latex)
    if len(parts) == 1:
        return [latex]
    out = [parts[0]]
    out.extend(parts[2::2])
    return [x.strip() for x in out if x.strip()]


def repair_page(
    page_json_path: str | Path,
    page_image_path: str | Path,
    marker_bin: str,
    llama_bin: str | None,
    work_dir: str | Path,
    timeout_seconds: int = 120,
    max_seconds: int = 300,
) -> dict:
    page_json_path = Path(page_json_path)
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    repaired = []
    deadline = time.monotonic() + max_seconds
    for block in page["blocks"]:
        if time.monotonic() >= deadline:
            break
        codes = {f["code"] for f in block.get("review_flags") or []}
        if not (codes & REPAIR_FLAGS) or "MATH_REPAIR_SKIPPED" in codes:
            continue
        try:
            repaired_result = _run_marker_on_crop(
                Path(page_image_path), block["bbox"], marker_bin, llama_bin,
                Path(work_dir) / block["block_id"],
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            block.setdefault("review_flags", []).append({
                "code": "MATH_REPAIR_SKIPPED",
                "severity": "info",
            })
            continue
        if not (repaired_result.get("latex") or []):
            block.setdefault("review_flags", []).append({
                "code": "MATH_REPAIR_SKIPPED",
                "severity": "info",
            })
            continue
        new_latex = []
        new_markdown = []
        for latex in repaired_result.get("latex") or []:
            new_latex.extend(_split_formula(normalize_latex(latex)))
        md = (repaired_result.get("markdown") or "").strip()
        if md:
            new_markdown.append(md)
        if not new_latex:
            continue
        old_latex = list(block.get("latex") or [])
        block["latex"] = new_latex
        block["latex_validation"] = [validate_latex(x).as_dict() for x in new_latex]
        if new_markdown:
            block["markdown"] = "\n\n".join(new_markdown)
        block["review_flags"] = [
            f for f in block.get("review_flags") or []
            if f["code"] not in REPAIR_FLAGS
        ]
        block["review_flags"].append({
            "code": "MATH_REPAIRED",
            "severity": "info",
            "old_latex": old_latex,
            "new_latex": new_latex,
        })
        if any("?" in x or "\\boxed{?}" in x for x in new_latex):
            block["review_flags"].append({
                "code": "FORMULA_PLACEHOLDER",
                "severity": "info",
            })
        fragment_re = re.compile(r"^\\(epsilon|notin|in|emptyset|ldots|mathbb\{Z\})$")
        fragments = [x for x in new_latex if fragment_re.match(x.strip())]
        if fragments:
            block["review_flags"].append({
                "code": "FORMULA_FRAGMENT",
                "severity": "warning",
                "fragments": fragments,
            })
        repaired.append({
            "block_id": block["block_id"],
            "old_latex": old_latex,
            "new_latex": new_latex,
        })
    page_json_path.write_text(
        json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"page": page["page_id"], "repaired": repaired}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--page-json", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--marker-bin", required=True)
    parser.add_argument("--llama-bin", default=os.environ.get("LLAMA_CPP_BINARY"))
    parser.add_argument("--work", required=True)
    args = parser.parse_args()
    result = repair_page(
        args.page_json, args.image, args.marker_bin, args.llama_bin, args.work
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["repaired"] else 1


if __name__ == "__main__":
    sys.exit(main())
