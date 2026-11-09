"""External page verifier for ingestion escalation.

A verifier receives a page image and the current canonical page JSON. It must
write a marker-compatible JSON page to ``IDP_OUTPUT_DIR/p<page>.json``. The
pipeline then re-runs extraction on that verified page and records provenance.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

VERIFY_CODES = {
    "WATERMARK_CANDIDATE_REVIEW",
    "PAGE_TEXT_LAYER_UNUSABLE",
    "PAGE_FAINT_CONTENT_REVIEW",
    "QUESTION_GROUP_REVIEW",
    "QUESTION_ORPHAN_OPTIONS",
    "TEXT_EXTERNAL_REVIEW",
    "TEXT_RECOGNIZER_DISAGREEMENT",
    "TEXT_RECOGNIZER_FAILED",
    "TEXT_RECOGNIZER_UNSUPPORTED_CHARACTERS",
    "TEXT_RECOGNIZER_BUDGET_EXHAUSTED",
    "TEXT_RECOGNIZER_IMAGE_UNAVAILABLE",
    "STRUCTURED_EXTRACTION_REVIEW",
    "STRUCTURED_REGION_UNRESOLVED",
    "STRUCTURED_LAYOUT_FAILED",
    "STRUCTURED_LAYOUT_DISAGREEMENT",
    "STRUCTURED_INVALID_BBOX",
    "STRUCTURED_BUDGET_EXHAUSTED",
    "STRUCTURED_PIXEL_LIMIT",
    "STRUCTURED_IMAGE_UNAVAILABLE",
    "TABLE_HEADER_UNKNOWN",
    "TABLE_OCR_REVIEW",
    "OCR_REGION_RECOVERED",
    "OCR_REGION_UNRESOLVED",
    "OCR_REGION_DISAGREEMENT",
    "OCR_REGION_DETECTION_FAILED",
    "OCR_REGION_BUDGET_EXHAUSTED",
    "OCR_REGION_FAILED",
    "OCR_REGION_INVALID_BBOX",
    "OCR_REGION_COMPLEX_CONTENT",
    "OCR_MODEL_TOKEN_LEAK",
    "PAGE_LAYOUT_FAILED",
    "PAGE_BLURRY",
    "PAGE_LOW_CONTRAST",
    "PAGE_NEEDS_DESKEW",
    "LATEX_INVALID",
    "FORMULA_INCOMPLETE",
    "FORMULA_SIGN_REVIEW",
    "FORMULA_SEMANTIC_REVIEW",
    "MATH_TEXT_INTEGRITY",
    "LOW_LAYOUT_CONFIDENCE",
    "EMPTY_BLOCK",
    "EMPTY_BLOCK_RECOVERED",
    "TEXT_DISAGREEMENT",
    "TEXT_ENCODING_REVIEW",
    "FAST_MODE_REVIEW",
    "FALLBACK_ENGINE_REVIEW",
}


def _command_argv(command: str) -> list[str]:
    return shlex.split(command, posix=(os.name != "nt"))


def needs_verification(page: dict) -> bool:
    if page.get("processing_status") == "layout_failed":
        return True
    codes = {
        flag.get("code")
        for flag in page.get("review") or []
        if flag.get("severity") in {"warning", "error"}
    }
    for block in page.get("blocks") or []:
        codes.update(
            flag.get("code")
            for flag in block.get("review_flags") or []
            if flag.get("severity") in {"warning", "error"}
        )
    return bool(codes & VERIFY_CODES)


def _validate_marker(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data.get("children") if isinstance(data, dict) else None
    if not isinstance(children, list) or not children:
        raise RuntimeError("verifier produced no page")
    page = children[0]
    if not isinstance(page, dict) or page.get("block_type") != "Page":
        raise RuntimeError("verifier must return a Page child")
    if not isinstance(page.get("children"), list) or not page["children"]:
        raise RuntimeError("verifier produced an empty page")
    return data


def verify_page(
    command: str,
    page_id: int,
    image_path: str | Path,
    page_json: str | Path,
    out_dir: str | Path,
    timeout: int = 600,
) -> tuple[Path, dict]:
    if not command.strip():
        raise RuntimeError("verifier command is empty")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["IDP_PAGE_ID"] = str(page_id)
    env["IDP_PAGE_IMAGE"] = str(Path(image_path).resolve())
    env["IDP_PAGE_JSON"] = str(Path(page_json).resolve())
    env["IDP_OUTPUT_DIR"] = str(out_dir.resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        _command_argv(command),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    target = out_dir / f"p{page_id:04d}.json"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1000:]
        raise RuntimeError(f"verifier exited {proc.returncode}: {detail}")
    if not target.exists():
        detail = (proc.stderr or proc.stdout or "").strip()[-1000:]
        raise RuntimeError(f"verifier did not write {target.name}: {detail}")
    data = _validate_marker(target)
    metadata = data.setdefault("metadata", {})
    metadata.setdefault("engine", "verifier")
    metadata.setdefault("kind", "verifier")
    metadata.setdefault("review_code", "VERIFIED_BY")
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target, metadata
